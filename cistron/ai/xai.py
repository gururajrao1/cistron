"""
Explainable AI attributions for Hill-cube pathway simulations.

Provides a fast SHAP / integrated-gradients *proxy* over the 5D node feature
vectors, attentive-flow decomposition of GAT αᵢⱼ, and lightweight
counterfactual what-if narratives — without re-running expensive path
integrals on every request.
"""

from __future__ import annotations

from typing import Dict, List, Mapping, Optional, Sequence, Tuple
import time

import numpy as np

from cistron.ai.prioritizer import (
    ATTENTION_EPS,
    resolve_output_nodes,
)
from cistron.models.graph import CausalActivityGraph
from cistron.models.prioritization import NodeFeatureVector, PrioritizationResult
from cistron.models.serialization import ScrubberPayload
from cistron.models.xai import (
    CounterfactualResult,
    EdgeFlowImpact,
    FeatureAttribution,
    NodeShapAttribution,
    XAIAttributionResult,
)
from cistron.serialization.scrubber import edge_flux_key

FEATURE_NAMES = ("y_init", "y_final", "delta_y", "capacity", "is_knocked_out")


def _mean_flux(series: Sequence[float]) -> float:
    if not series:
        return 0.0
    return float(np.mean(np.asarray(series, dtype=float)))


def _activity_at(payload: ScrubberPayload, node: str, t_min: float) -> float:
    times = payload.time_steps
    traj = payload.nodes.get(node)
    if not times or not traj:
        return 0.0
    if t_min <= times[0]:
        return float(traj[0])
    if t_min >= times[-1]:
        return float(traj[-1])
    # Linear lerp
    for i in range(1, len(times)):
        if times[i] >= t_min:
            t0, t1 = times[i - 1], times[i]
            y0, y1 = float(traj[i - 1]), float(traj[i])
            w = 0.0 if t1 <= t0 else (t_min - t0) / (t1 - t0)
            return y0 + w * (y1 - y0)
    return float(traj[-1])


def _outgoing_attention(
    graph: CausalActivityGraph,
    node: str,
    attention: Mapping[str, float],
) -> float:
    total = 0.0
    for edge in graph.edges:
        if edge.source == node:
            total += float(attention.get(edge_flux_key(edge.source, edge.target), 0.0))
    return total


def _incoming_edges(
    graph: CausalActivityGraph, node: str
) -> List[Tuple[str, str]]:
    return [(e.source, e.target) for e in graph.edges if e.target == node]


def _outgoing_edges(
    graph: CausalActivityGraph, node: str
) -> List[Tuple[str, str]]:
    return [(e.source, e.target) for e in graph.edges if e.source == node]


def _feature_vector(vec: NodeFeatureVector) -> np.ndarray:
    return np.asarray(
        [
            float(vec.y_init),
            float(vec.y_final),
            float(vec.delta_y),
            float(vec.capacity),
            1.0 if vec.is_knocked_out else 0.0,
        ],
        dtype=float,
    )


def _ig_feature_attributions(
    features: np.ndarray,
    *,
    node_importance: float,
    baseline: Optional[np.ndarray] = None,
) -> List[FeatureAttribution]:
    """
    Integrated-gradients proxy along the straight line from a zero/basal
    baseline to the observed 5D feature vector.

    Attribution mass is redistributed proportionally to |f_k − baseline_k|
    and signed by the direction of change, then scaled so Σ|φ_k| ≈ |importance|.
    """
    base = baseline if baseline is not None else np.zeros(5, dtype=float)
    # Knockout baseline treats capacity=1, is_ko=0 as unperturbed
    if baseline is None:
        base = np.array([0.0, 0.0, 0.0, 1.0, 0.0], dtype=float)
    delta = features - base
    weights = np.abs(delta)
    denom = float(weights.sum()) + ATTENTION_EPS
    signed = np.sign(delta)
    # Capacity reduction and KO are negative for pathway drive when importance > 0
    signed[3] = -1.0 if features[3] < base[3] else (1.0 if features[3] > base[3] else 0.0)
    signed[4] = -1.0 if features[4] > 0.5 else 0.0
    raw = signed * weights / denom * abs(node_importance)
    # Preserve importance sign on the dominant feature
    if node_importance < 0:
        raw = -np.abs(raw)
    else:
        # Keep capacity/KO negative when they suppress activity
        pass
    out: List[FeatureAttribution] = []
    for name, val, attr in zip(FEATURE_NAMES, features, raw):
        out.append(
            FeatureAttribution(
                feature_name=name,
                value=float(val),
                attribution=float(attr),
            )
        )
    return out


def _node_importance(
    graph: CausalActivityGraph,
    node: str,
    vec: NodeFeatureVector,
    attention: Mapping[str, float],
    output_set: set,
) -> float:
    """
    Marginal contribution proxy to Σ Δy_output:

    φ_i = sign(Δy_i) · |Δy_i| · w̃_i · (α_out + 𝟙_{i∈outputs})
    """
    w_tilde = 0.0 if vec.is_knocked_out else max(0.0, float(vec.capacity))
    alpha_out = _outgoing_attention(graph, node, attention)
    output_bonus = 1.0 if node in output_set else 0.0
    drive = abs(float(vec.delta_y)) * (alpha_out + 0.35 * output_bonus + ATTENTION_EPS)
    signed = float(np.sign(vec.delta_y) or 1.0) * drive * (0.25 + 0.75 * w_tilde)
    if vec.is_knocked_out:
        # Knockouts contribute negative importance equal to lost capacity drive
        signed = -abs(drive) * 0.85
    return float(signed)


def decompose_attentive_flow(
    graph: CausalActivityGraph,
    payload: ScrubberPayload,
    prioritization: PrioritizationResult,
    *,
    top_k: int = 20,
) -> List[EdgeFlowImpact]:
    """Rank edges by αᵢⱼ × |Δy_source| × mean Hill flux."""
    attention = prioritization.attention_matrix
    vectors = prioritization.node_vectors
    impacts: List[EdgeFlowImpact] = []
    for edge in graph.edges:
        key = edge_flux_key(edge.source, edge.target)
        alpha = float(attention.get(key, 0.0))
        src_vec = vectors.get(edge.source)
        delta = abs(float(src_vec.delta_y)) if src_vec else 0.0
        flux = _mean_flux(payload.edges.get(key) or [])
        score = alpha * (0.4 + 0.6 * delta) * (0.2 + 0.8 * flux)
        impacts.append(
            EdgeFlowImpact(
                edge_key=key,
                source=edge.source,
                target=edge.target,
                alpha=alpha,
                impact_score=float(score),
                mean_flux=flux,
            )
        )
    impacts.sort(key=lambda e: (-e.impact_score, e.edge_key))
    return impacts[:top_k]


def _counterfactual_for_node(
    graph: CausalActivityGraph,
    payload: ScrubberPayload,
    prioritization: PrioritizationResult,
    node: str,
    *,
    readout: str,
    horizon_min: float = 15.0,
) -> CounterfactualResult:
    """
    Analytical what-if: restore capacity to 1.0 (if suppressed) or apply KO.

    Uses local sensitivity: Δy_readout ≈ α_path · Δw · y_readout_scale without
    a second ODE solve (keeps XAI under the latency budget).
    """
    vec = prioritization.node_vectors.get(node)
    attention = prioritization.attention_matrix
    y_read_t = _activity_at(payload, readout, horizon_min)
    y_read_60 = float(
        (payload.nodes.get(readout) or [0.0])[-1]
        if payload.nodes.get(readout)
        else 0.0
    )
    baseline = y_read_t if y_read_t > 0 else y_read_60

    if vec is None:
        return CounterfactualResult(
            hypothesis=f"Insufficient state for {node}",
            node=node,
            intervention="none",
            readout_node=readout,
            baseline_readout=baseline,
            counterfactual_readout=baseline,
            fold_change=1.0,
            delta_absolute=0.0,
            horizon_min=horizon_min,
            narrative=f"No feature vector available for {node}.",
        )

    # Path coupling: direct attention or 1-hop product
    direct = float(attention.get(edge_flux_key(node, readout), 0.0))
    coupling = direct
    if coupling < 1e-6:
        # 1-hop via intermediates
        for mid_src, mid_tgt in _outgoing_edges(graph, node):
            a1 = float(attention.get(edge_flux_key(mid_src, mid_tgt), 0.0))
            a2 = float(attention.get(edge_flux_key(mid_tgt, readout), 0.0))
            coupling = max(coupling, a1 * a2)
    coupling = max(coupling, 0.08)  # residual pathway leakage floor

    if vec.is_knocked_out or vec.capacity < 0.5:
        intervention = "restore_capacity_1.0"
        lost_w = 1.0 - (0.0 if vec.is_knocked_out else float(vec.capacity))
        # Expected readout lift scales with lost capacity × coupling × headroom
        headroom = max(0.05, 1.0 - baseline)
        delta = coupling * lost_w * headroom * (0.55 + 0.45 * abs(vec.delta_y))
        cf = min(1.0, baseline + delta)
        fold = (cf / baseline) if baseline > 1e-6 else (cf / 1e-6)
        narrative = (
            f"If {node} capacity were restored to 1.0, downstream {readout} "
            f"activity would increase by {fold:.1f}× within {horizon_min:.0f} minutes "
            f"(Δy ≈ {delta:+.3f} via attentive coupling α≈{coupling:.2f})."
        )
    else:
        intervention = "knockout_w_0"
        # KO suppresses readout proportional to coupling × current drive
        delta = -coupling * float(vec.capacity) * baseline * (0.4 + 0.6 * abs(vec.delta_y))
        cf = max(0.0, baseline + delta)
        fold = (cf / baseline) if baseline > 1e-6 else 0.0
        narrative = (
            f"If {node} were knocked out (wᵢ=0), downstream {readout} activity "
            f"would fall to {fold:.1f}× of baseline within {horizon_min:.0f} minutes "
            f"(Δy ≈ {delta:+.3f})."
        )

    return CounterfactualResult(
        hypothesis=narrative,
        node=node,
        intervention=intervention,
        readout_node=readout,
        baseline_readout=float(baseline),
        counterfactual_readout=float(cf),
        fold_change=float(fold),
        delta_absolute=float(cf - baseline),
        horizon_min=horizon_min,
        narrative=narrative,
    )


def compute_xai_attributions(
    graph: CausalActivityGraph,
    payload: ScrubberPayload,
    prioritization: PrioritizationResult,
    *,
    output_nodes: Optional[Sequence[str]] = None,
    top_n_nodes: int = 12,
    top_n_edges: int = 16,
    n_counterfactuals: int = 3,
    horizon_min: float = 15.0,
) -> XAIAttributionResult:
    """
    Compute SHAP/IG-proxy node attributions, attentive flow ranks, and
    counterfactual what-if narratives for the current simulation.
    """
    t0 = time.perf_counter()
    outputs = resolve_output_nodes(graph, output_nodes=output_nodes)
    output_set = set(outputs)

    output_delta_sum = 0.0
    for sym in outputs:
        vec = prioritization.node_vectors.get(sym)
        if vec is not None:
            output_delta_sum += float(vec.delta_y)

    # Node SHAP importance
    raw: List[Tuple[str, float, NodeFeatureVector]] = []
    for sym, vec in prioritization.node_vectors.items():
        imp = _node_importance(
            graph, sym, vec, prioritization.attention_matrix, output_set
        )
        raw.append((sym, imp, vec))
    raw.sort(key=lambda r: (-abs(r[1]), r[0]))

    node_attrs: List[NodeShapAttribution] = []
    for rank, (sym, imp, vec) in enumerate(raw[:top_n_nodes], start=1):
        feats = _feature_vector(vec)
        node_attrs.append(
            NodeShapAttribution(
                node=sym,
                importance=float(imp),
                rank=rank,
                feature_attributions=_ig_feature_attributions(feats, node_importance=imp),
                delta_y=float(vec.delta_y),
                capacity=float(vec.capacity),
                is_knocked_out=bool(vec.is_knocked_out),
            )
        )

    edge_impacts = decompose_attentive_flow(
        graph, payload, prioritization, top_k=top_n_edges
    )

    readout = outputs[0] if outputs else (
        sorted(graph.nodes.keys())[-1] if graph.nodes else "OUT"
    )
    # Prefer non-readout top drivers for counterfactuals
    cf_candidates = [
        sym
        for sym, _, _ in raw
        if sym != readout
    ][: max(n_counterfactuals * 2, n_counterfactuals)]
    counterfactuals: List[CounterfactualResult] = []
    for sym in cf_candidates:
        if len(counterfactuals) >= n_counterfactuals:
            break
        counterfactuals.append(
            _counterfactual_for_node(
                graph,
                payload,
                prioritization,
                sym,
                readout=readout,
                horizon_min=horizon_min,
            )
        )

    return XAIAttributionResult(
        node_attributions=node_attrs,
        edge_flow_impacts=edge_impacts,
        counterfactuals=counterfactuals,
        output_nodes=list(outputs),
        output_delta_sum=float(output_delta_sum),
        elapsed_ms=(time.perf_counter() - t0) * 1000.0,
        metadata={
            "method": "shap_ig_proxy_v1",
            "n_nodes_scored": len(raw),
            "simulation_id": payload.simulation_id,
        },
    )


__all__ = [
    "FEATURE_NAMES",
    "compute_xai_attributions",
    "decompose_attentive_flow",
]
