"""
AI target prioritization and dynamic-flow graph attention.

Builds 5D time-aware node vectors ``h_i`` from a :class:`ScrubberPayload`,
computes trapezoidal attention coefficients ``α_ij`` over edge flux, ranks
master-regulator drivers ``S_i``, and evaluates synthetic-lethal dual
inhibition pairs (Domain 10).
"""

from __future__ import annotations

from itertools import combinations
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

import numpy as np

from voidsignal.engine.solver import (
    STRUCTURAL_OUTPUT_GENES,
    HillCubeConfig,
    HillCubeEngine,
)
from voidsignal.models.graph import CausalActivityGraph
from voidsignal.models.prioritization import (
    CombinationCandidate,
    NodeFeatureVector,
    PrioritizationResult,
)
from voidsignal.models.serialization import ScrubberPayload
from voidsignal.serialization.scrubber import edge_flux_key, scrub_simulation

ATTENTION_EPS = 1e-8


def _trapz(y: np.ndarray, x: np.ndarray) -> float:
    """``numpy.trapezoid`` with ``trapz`` fallback."""
    fn = getattr(np, "trapezoid", None) or getattr(np, "trapz")
    return float(fn(y, x=x))


def _payload_weights(payload: ScrubberPayload) -> Dict[str, float]:
    meta = payload.metadata or {}
    weights = meta.get("weights") or {}
    if isinstance(weights, Mapping):
        return {str(k): float(v) for k, v in weights.items()}
    return {}


def _payload_knockouts(payload: ScrubberPayload) -> Set[str]:
    meta = payload.metadata or {}
    kos: Set[str] = set()
    engine = meta.get("engine") or {}
    if isinstance(engine, Mapping):
        for k in engine.get("knockouts") or []:
            kos.add(str(k))
    for k in meta.get("knockouts") or []:
        kos.add(str(k))
    # Capacity-zero nodes count as knocked out
    for sym, w in _payload_weights(payload).items():
        if float(w) <= 0.0:
            kos.add(sym)
    return kos


def _payload_clamps(payload: ScrubberPayload) -> Dict[str, float]:
    meta = payload.metadata or {}
    engine = meta.get("engine") or {}
    clamped = {}
    if isinstance(engine, Mapping):
        raw = engine.get("clamped") or {}
        if isinstance(raw, Mapping):
            clamped = {str(k): float(v) for k, v in raw.items()}
    return clamped


def build_node_feature_vector(
    symbol: str,
    trajectory: Sequence[float],
    *,
    capacity: float = 1.0,
    is_knocked_out: bool = False,
) -> NodeFeatureVector:
    """Construct the 5D feature schema from a keyframe activity series."""
    if not trajectory:
        y0 = y1 = 0.0
    else:
        y0 = float(trajectory[0])
        y1 = float(trajectory[-1])
    return NodeFeatureVector(
        y_init=y0,
        y_final=y1,
        delta_y=y1 - y0,
        capacity=float(max(0.0, min(1.0, capacity))),
        is_knocked_out=bool(is_knocked_out),
    )


def node_feature_array(vec: NodeFeatureVector) -> np.ndarray:
    """NumPy view of ``h_i = [y0, y60, Δy, w, is_ko]``."""
    return np.asarray(vec.as_array(), dtype=float)


def compute_attention_matrix(
    graph: CausalActivityGraph,
    payload: ScrubberPayload,
    *,
    eps: float = ATTENTION_EPS,
) -> Dict[str, float]:
    """
    Dynamic-flow attention ``α_ij`` for each directed edge ``j → i``.

    Uses trapezoidal integration of scrubber edge flux over ``time_steps``.
    Incoming attentions to any node sum to 1 (within floating tolerance).
    """
    times = np.asarray(payload.time_steps, dtype=float)
    # Integrated flux per edge key
    integrated: Dict[str, float] = {}
    for edge in graph.edges:
        key = edge_flux_key(edge.source, edge.target)
        flux = payload.edges.get(key)
        if flux is None:
            integrated[key] = 0.0
            continue
        y = np.asarray(flux, dtype=float)
        if y.size != times.size:
            # Align by truncating to shared length
            n = min(y.size, times.size)
            integrated[key] = _trapz(y[:n], times[:n]) if n >= 2 else float(y[0]) * 0.0
        else:
            integrated[key] = _trapz(y, times) if times.size >= 2 else 0.0

    # Group incoming edges by target
    incoming: Dict[str, List[Tuple[str, str]]] = {}
    for edge in graph.edges:
        incoming.setdefault(edge.target, []).append((edge.source, edge.target))

    alphas: Dict[str, float] = {}
    for target, pairs in incoming.items():
        denom = eps
        keyed: List[Tuple[str, float]] = []
        for src, tgt in pairs:
            key = edge_flux_key(src, tgt)
            integ = max(0.0, float(integrated.get(key, 0.0)))
            keyed.append((key, integ))
            denom += integ
        for key, integ in keyed:
            alphas[key] = integ / denom

    # Edges with no shared target group already covered; orphans get 0
    for edge in graph.edges:
        key = edge_flux_key(edge.source, edge.target)
        alphas.setdefault(key, 0.0)

    return alphas


def compute_driver_scores(
    graph: CausalActivityGraph,
    node_vectors: Mapping[str, NodeFeatureVector],
    attention_matrix: Mapping[str, float],
) -> List[Tuple[str, float]]:
    """
    Master-regulator driver score

    ``S_i = |Δy_i| · Σ_{m ∈ N_out(i)} α_{m←i}``

    where ``α`` on outgoing edge ``i → m`` is stored under ``"i->m"``.
    """
    out_neighbors: Dict[str, List[str]] = {sym: [] for sym in graph.nodes}
    for edge in graph.edges:
        out_neighbors.setdefault(edge.source, []).append(edge.target)
        out_neighbors.setdefault(edge.target, [])

    scores: List[Tuple[str, float]] = []
    symbols = sorted(set(graph.nodes.keys()) | set(node_vectors.keys()))
    for sym in symbols:
        vec = node_vectors.get(sym)
        delta = abs(float(vec.delta_y)) if vec is not None else 0.0
        attn_out = 0.0
        for tgt in out_neighbors.get(sym, []):
            attn_out += float(attention_matrix.get(edge_flux_key(sym, tgt), 0.0))
        scores.append((sym, float(delta * attn_out)))

    scores.sort(key=lambda p: (-p[1], p[0]))
    return scores


def prioritize(
    graph: CausalActivityGraph,
    payload: ScrubberPayload,
    *,
    eps: float = ATTENTION_EPS,
) -> PrioritizationResult:
    """
    Full prioritization pass: 5D vectors, attention matrix, ranked drivers.
    """
    weights = _payload_weights(payload)
    knockouts = _payload_knockouts(payload)

    node_vectors: Dict[str, NodeFeatureVector] = {}
    symbols = sorted(set(payload.nodes.keys()) | set(graph.nodes.keys()))
    for sym in symbols:
        traj = payload.nodes.get(sym) or [0.0]
        if sym in weights:
            cap = float(weights[sym])
        elif sym in graph.nodes:
            cap = float(graph.nodes[sym].activity_weight)
        else:
            cap = 1.0
        ko = sym in knockouts or cap <= 0.0
        if ko:
            cap = 0.0
        node_vectors[sym] = build_node_feature_vector(
            sym, traj, capacity=cap, is_knocked_out=ko
        )

    attention = compute_attention_matrix(graph, payload, eps=eps)
    drivers = compute_driver_scores(graph, node_vectors, attention)

    return PrioritizationResult(
        node_vectors=node_vectors,
        attention_matrix=attention,
        master_regulators=drivers,
        metadata={
            "simulation_id": payload.simulation_id,
            "graph_name": graph.name,
            "n_nodes": len(node_vectors),
            "n_edges": len(attention),
            "eps": float(eps),
        },
    )


def resolve_output_nodes(
    graph: CausalActivityGraph,
    *,
    output_nodes: Optional[Sequence[str]] = None,
) -> List[str]:
    """
    Pathway readout genes for combination scoring.

    Preference order: explicit ``output_nodes`` → structural outputs present
    in the graph → sinks (nodes with out-degree 0).
    """
    if output_nodes:
        return [str(s) for s in output_nodes]

    present = [s for s in sorted(STRUCTURAL_OUTPUT_GENES) if s in graph.nodes]
    # Also accept common aliases already in the graph
    for alias, canon in (("VEGF", "VEGFA"), ("SLC2A1", "GLUT1")):
        if alias in graph.nodes and canon not in present:
            present.append(alias)
    if present:
        return present

    out_deg: Dict[str, int] = {s: 0 for s in graph.nodes}
    for e in graph.edges:
        out_deg[e.source] = out_deg.get(e.source, 0) + 1
        out_deg.setdefault(e.target, 0)
    sinks = [s for s, d in out_deg.items() if d == 0]
    return sorted(sinks) if sinks else sorted(graph.nodes.keys())


def output_sum_at_final(
    payload: ScrubberPayload,
    output_nodes: Sequence[str],
) -> float:
    """Σ y_output(t_60) over the requested readout genes."""
    total = 0.0
    for sym in output_nodes:
        traj = payload.nodes.get(sym)
        if not traj:
            continue
        total += float(traj[-1])
    return float(total)


def _simulate_knockout_payload(
    graph: CausalActivityGraph,
    *,
    knockouts: Sequence[str],
    clamps: Optional[Mapping[str, float]] = None,
    t_end: float = 60.0,
    base_knockouts: Optional[Iterable[str]] = None,
    dense_output_points: int = 61,
) -> ScrubberPayload:
    eng = HillCubeEngine(
        graph,
        config=HillCubeConfig(
            t_end=t_end,
            dense_output_points=max(2, int(dense_output_points)),
        ),
    )
    if clamps:
        for sym, val in clamps.items():
            if sym in eng.symbols:
                eng.clamp(sym, float(val))
    kos = list(base_knockouts or [])
    kos.extend(list(knockouts))
    if kos:
        eng.knockout(kos)
    return scrub_simulation(eng, t_end=t_end)


def rank_combination_targets(
    graph: CausalActivityGraph,
    payload: ScrubberPayload,
    *,
    candidates: Optional[Sequence[str]] = None,
    output_nodes: Optional[Sequence[str]] = None,
    top_k: Optional[int] = None,
    t_end: float = 60.0,
) -> List[CombinationCandidate]:
    """
    Rank unordered target pairs by dual-inhibition pathway suppression.

    For each pair ``(a, b)`` re-simulates with both nodes knocked out and
    scores ``Σ y_output(t_60)``. Synergy uses a Bliss-style residual:

    ``synergy = E[ab]_indep − y_ab``, where independent expectation is
    ``y_a · y_b / y_0`` (clamped), so positive synergy ⇒ combo beats
    independence.
    """
    outputs = resolve_output_nodes(graph, output_nodes=output_nodes)
    clamps = _payload_clamps(payload)
    base_kos = _payload_knockouts(payload)

    if candidates is None:
        # Exclude pure inputs that are clamped and structural outputs themselves
        skip = set(clamps.keys()) | set(outputs) | base_kos
        candidates = [s for s in sorted(graph.nodes.keys()) if s not in skip]
        if len(candidates) < 2:
            candidates = [s for s in sorted(graph.nodes.keys()) if s not in base_kos]

    cand = [str(c) for c in candidates]
    if len(cand) < 2:
        return []

    y0 = output_sum_at_final(payload, outputs)
    # Cache single-KO scores
    single_cache: Dict[str, float] = {}

    def _single(sym: str) -> float:
        if sym not in single_cache:
            p = _simulate_knockout_payload(
                graph,
                knockouts=[sym],
                clamps=clamps,
                t_end=t_end,
                base_knockouts=base_kos,
            )
            single_cache[sym] = output_sum_at_final(p, outputs)
        return single_cache[sym]

    ranked: List[CombinationCandidate] = []
    for a, b in combinations(sorted(set(cand)), 2):
        combo_payload = _simulate_knockout_payload(
            graph,
            knockouts=[a, b],
            clamps=clamps,
            t_end=t_end,
            base_knockouts=base_kos,
        )
        y_ab = output_sum_at_final(combo_payload, outputs)
        y_a = _single(a)
        y_b = _single(b)
        if y0 > ATTENTION_EPS:
            bliss = (y_a * y_b) / y0
        else:
            bliss = min(y_a, y_b)
        synergy = float(bliss - y_ab)
        ranked.append(
            CombinationCandidate(
                target_a=a,
                target_b=b,
                output_sum=y_ab,
                baseline_output_sum=y0,
                single_a_output_sum=y_a,
                single_b_output_sum=y_b,
                synergy_score=synergy,
            )
        )

    # Primary: minimize dual output; tie-break by synergy descending
    ranked.sort(key=lambda c: (c.output_sum, -c.synergy_score, c.target_a, c.target_b))
    if top_k is not None:
        ranked = ranked[: max(0, int(top_k))]
    return ranked


__all__ = [
    "ATTENTION_EPS",
    "CombinationCandidate",
    "NodeFeatureVector",
    "PrioritizationResult",
    "build_node_feature_vector",
    "compute_attention_matrix",
    "compute_driver_scores",
    "node_feature_array",
    "output_sum_at_final",
    "prioritize",
    "rank_combination_targets",
    "resolve_output_nodes",
]
