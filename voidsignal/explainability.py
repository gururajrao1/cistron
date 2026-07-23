"""
Explainable AI for VOIDSIGNAL Phase 5 graph intelligence.

Attributes target / link predictions to node features, edges, feedback loops,
and compartment bottlenecks using integrated-gradients-style path integrals and
attention-/message-based structural rationales.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple
import logging
import math

from voidsignal.graph_ml import GraphTensors
from voidsignal.predictive_models import (
    LinkPredictionModel,
    TargetDiscoveryModel,
    _norm,
    _sigmoid,
)
from voidsignal.topology import SignalingNetwork

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Attribution records
# ---------------------------------------------------------------------------


@dataclass
class FeatureAttribution:
    """Per-feature integrated gradient for one node."""

    feature_name: str
    value: float
    attribution: float

    def as_dict(self) -> Dict[str, Any]:
        return {
            "feature_name": self.feature_name,
            "value": self.value,
            "attribution": self.attribution,
        }


@dataclass
class EdgeAttribution:
    edge_id: str
    source_id: str
    target_id: str
    source_name: str
    target_name: str
    attribution: float
    attention: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "source_name": self.source_name,
            "target_name": self.target_name,
            "attribution": self.attribution,
            "attention": self.attention,
        }


@dataclass
class StructuralRationale:
    """Topological / spatial structures supporting a prediction."""

    feedback_loops: List[List[str]]
    feedback_loop_names: List[List[str]]
    hubs: List[Tuple[str, str, float]]
    """(entity_id, name, hub_score)"""
    compartment_bottlenecks: List[Dict[str, Any]]
    cluster_ids: Dict[str, int]
    notes: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "feedback_loops": self.feedback_loops,
            "feedback_loop_names": self.feedback_loop_names,
            "hubs": [
                {"entity_id": e, "name": n, "score": s} for e, n, s in self.hubs
            ],
            "compartment_bottlenecks": list(self.compartment_bottlenecks),
            "cluster_ids": dict(self.cluster_ids),
            "notes": list(self.notes),
        }


@dataclass
class ExplanationReport:
    """Full rationale for one AI Scientist recommendation."""

    entity_id: str
    name: str
    score: float
    feature_attributions: List[FeatureAttribution]
    edge_attributions: List[EdgeAttribution]
    structural: StructuralRationale
    summary: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "name": self.name,
            "score": self.score,
            "summary": self.summary,
            "feature_attributions": [f.as_dict() for f in self.feature_attributions],
            "edge_attributions": [e.as_dict() for e in self.edge_attributions],
            "structural": self.structural.as_dict(),
        }


# ---------------------------------------------------------------------------
# Integrated gradients (finite-difference path integral)
# ---------------------------------------------------------------------------


def _score_fn_target(
    model: TargetDiscoveryModel,
    tensors: GraphTensors,
    row: int,
) -> float:
    emb = model.encoder.encode(tensors)
    if model.head is None:
        return _sigmoid(_norm(emb[row]) - 1.0)
    return model.head.score(emb[row])


def integrated_gradients_node(
    model: TargetDiscoveryModel,
    tensors: GraphTensors,
    entity_id: str,
    *,
    steps: int = 24,
    baseline: str = "zero",
) -> List[FeatureAttribution]:
    """
    Path-integrated feature attributions for a target node::

        IG_k = (x_k − x'_k) · ∫₀¹ ∂F(x' + α(x−x'))/∂x_k dα

    approximated with Riemann sums and central finite differences.
    """
    if steps < 2:
        raise ValueError("steps must be ≥ 2")
    row = tensors.row_of(entity_id)
    x = tensors.x[row][:]
    f = len(x)
    if baseline == "zero":
        x0 = [0.0] * f
    elif baseline == "mean":
        n = tensors.num_nodes
        x0 = [sum(tensors.x[i][j] for i in range(n)) / max(n, 1) for j in range(f)]
    else:
        raise ValueError("baseline must be 'zero' or 'mean'")

    grads_acc = [0.0] * f
    eps = 1e-3
    for s in range(1, steps + 1):
        alpha = s / steps
        probe = tensors.clone()
        probe.x[row] = [x0[j] + alpha * (x[j] - x0[j]) for j in range(f)]
        # Finite-difference gradient w.r.t. each feature at this alpha
        base_score = _score_fn_target(model, probe, row)
        for j in range(f):
            plus = probe.clone()
            plus.x[row][j] += eps
            minus = probe.clone()
            minus.x[row][j] -= eps
            g = (_score_fn_target(model, plus, row) - _score_fn_target(model, minus, row)) / (
                2.0 * eps
            )
            grads_acc[j] += g
            # restore numerical sanity if encoder is discontinuous
            if not math.isfinite(grads_acc[j]):
                grads_acc[j] = 0.0

    ig = [(x[j] - x0[j]) * (grads_acc[j] / steps) for j in range(f)]
    names = tensors.node_feature_names
    out = [
        FeatureAttribution(
            feature_name=names[j] if j < len(names) else f"f{j}",
            value=x[j],
            attribution=ig[j],
        )
        for j in range(f)
    ]
    out.sort(key=lambda a: abs(a.attribution), reverse=True)
    return out


def edge_occlusion_attributions(
    model: TargetDiscoveryModel,
    tensors: GraphTensors,
    entity_id: str,
    network: SignalingNetwork,
    *,
    top_k: int = 8,
) -> List[EdgeAttribution]:
    """
    Edge importance via occlusion: Δscore when an edge's attributes are zeroed
    and its endpoints are briefly disconnected in the tensor pack.
    """
    row = tensors.row_of(entity_id)
    base = _score_fn_target(model, tensors, row)
    attn = list(model.encoder.last_attention)
    attrs: List[EdgeAttribution] = []
    m_edges = tensors.num_edges
    for m in range(m_edges):
        sid = tensors.node_id(tensors.edge_index[0][m])
        tid = tensors.node_id(tensors.edge_index[1][m])
        probe = tensors.clone()
        if probe.edge_attr:
            probe.edge_attr[m] = [0.0] * len(probe.edge_attr[m])
        # Soft-drop: collapse to a self-loop on the focus node
        probe.edge_index[0][m] = row
        probe.edge_index[1][m] = row
        delta = base - _score_fn_target(model, probe, row)
        attrs.append(
            EdgeAttribution(
                edge_id=tensors.edge_ids[m],
                source_id=sid,
                target_id=tid,
                source_name=network.registry.get(sid).name,
                target_name=network.registry.get(tid).name,
                attribution=delta,
                attention=attn[m] if m < len(attn) else 0.0,
            )
        )
    attrs.sort(key=lambda e: abs(e.attribution), reverse=True)
    return attrs[:top_k]


# ---------------------------------------------------------------------------
# Structural mapping (Phase 3/4 bridges)
# ---------------------------------------------------------------------------


def _connected_components(tensors: GraphTensors) -> Dict[str, int]:
    n = tensors.num_nodes
    parent = list(range(n))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for s, t in zip(tensors.edge_index[0], tensors.edge_index[1]):
        union(s, t)
    roots = {find(i): k for k, i in enumerate(sorted(set(find(i) for i in range(n))))}
    return {tensors.node_id(i): roots[find(i)] for i in range(n)}


def build_structural_rationale(
    network: SignalingNetwork,
    tensors: GraphTensors,
    focus_id: str,
    *,
    max_loops: int = 5,
) -> StructuralRationale:
    loops = network.detect_feedback_loops(max_length=8)
    # Prefer loops containing the focus node
    ranked = sorted(loops, key=lambda cyc: (0 if focus_id in cyc else 1, len(cyc)))
    selected = ranked[:max_loops]
    loop_names: List[List[str]] = []
    for cyc in selected:
        loop_names.append(
            [network.registry.get(nid).name if nid in network.registry else nid for nid in cyc]
        )

    hubs_raw = network.find_hubs(top_k=min(8, tensors.num_nodes))
    hubs = [
        (hid, network.registry.get(hid).name, float(score))
        for hid, score in hubs_raw
    ]

    # Compartment bottlenecks: edges whose endpoints differ in compartment_rank feature
    bottlenecks: List[Dict[str, Any]] = []
    feat_names = tensors.node_feature_names
    rank_idx = None
    for i, nm in enumerate(feat_names):
        if nm == "compartment_rank":
            rank_idx = i
            break
    if rank_idx is not None:
        for m, (s, t) in enumerate(zip(tensors.edge_index[0], tensors.edge_index[1])):
            rs = tensors.x[s][rank_idx]
            rt = tensors.x[t][rank_idx]
            if abs(rs - rt) > 0.5:
                sid = tensors.node_id(s)
                tid = tensors.node_id(t)
                bottlenecks.append(
                    {
                        "edge_id": tensors.edge_ids[m],
                        "source": network.registry.get(sid).name,
                        "target": network.registry.get(tid).name,
                        "source_rank": rs,
                        "target_rank": rt,
                        "gap": abs(rs - rt),
                    }
                )
        bottlenecks.sort(key=lambda b: b["gap"], reverse=True)
        bottlenecks = bottlenecks[:8]

    notes: List[str] = []
    if any(focus_id in cyc for cyc in selected):
        notes.append("Focus node participates in one or more feedback loops.")
    if any(h[0] == focus_id for h in hubs):
        notes.append("Focus node is a topological hub (high degree centrality).")
    if bottlenecks:
        notes.append("Cross-compartment edges detected — potential trafficking bottlenecks.")
    disease = network.metadata.get("disease_phenotype")
    if disease:
        notes.append(f"Network tagged with disease phenotype {disease!r}.")

    return StructuralRationale(
        feedback_loops=selected,
        feedback_loop_names=loop_names,
        hubs=hubs,
        compartment_bottlenecks=bottlenecks,
        cluster_ids=_connected_components(tensors),
        notes=notes,
    )


def _compose_summary(
    name: str,
    score: float,
    features: Sequence[FeatureAttribution],
    edges: Sequence[EdgeAttribution],
    structural: StructuralRationale,
) -> str:
    top_feats = ", ".join(f"{f.feature_name}={f.attribution:+.3f}" for f in features[:3])
    top_edge = edges[0] if edges else None
    edge_txt = (
        f" Critical edge {top_edge.source_name}→{top_edge.target_name} "
        f"(Δ={top_edge.attribution:+.3f})."
        if top_edge
        else ""
    )
    loop_txt = ""
    if structural.feedback_loop_names:
        loop_txt = " Feedback context: " + " / ".join(
            "→".join(cyc[:4]) for cyc in structural.feedback_loop_names[:2]
        )
        loop_txt += "."
    return (
        f"Prioritize {name} (score={score:.3f}). "
        f"Top features: {top_feats or 'n/a'}."
        f"{edge_txt}{loop_txt}"
    )


# ---------------------------------------------------------------------------
# Public explainer
# ---------------------------------------------------------------------------


class GraphExplainer:
    """
    Trace high-scoring target predictions to features + Phase-3/4 structure.
    """

    def __init__(
        self,
        model: TargetDiscoveryModel,
        *,
        ig_steps: int = 20,
        edge_top_k: int = 6,
    ) -> None:
        self.model = model
        self.ig_steps = ig_steps
        self.edge_top_k = edge_top_k

    def explain_target(
        self,
        tensors: GraphTensors,
        network: SignalingNetwork,
        entity_id: str,
        *,
        score: Optional[float] = None,
    ) -> ExplanationReport:
        # Warm encoder attention state
        _ = self.model.encoder.encode(tensors)
        if score is None:
            score = _score_fn_target(self.model, tensors, tensors.row_of(entity_id))
        name = (
            network.registry.get(entity_id).name
            if entity_id in network.registry
            else entity_id
        )
        feats = integrated_gradients_node(
            self.model, tensors, entity_id, steps=self.ig_steps
        )
        edges = edge_occlusion_attributions(
            self.model, tensors, entity_id, network, top_k=self.edge_top_k
        )
        structural = build_structural_rationale(network, tensors, entity_id)
        summary = _compose_summary(name, score, feats, edges, structural)
        return ExplanationReport(
            entity_id=entity_id,
            name=name,
            score=score,
            feature_attributions=feats,
            edge_attributions=edges,
            structural=structural,
            summary=summary,
        )

    def explain_top_targets(
        self,
        tensors: GraphTensors,
        network: SignalingNetwork,
        *,
        top_k: int = 3,
    ) -> List[ExplanationReport]:
        ranked = self.model.rank(tensors, network, top_k=top_k)
        return [
            self.explain_target(tensors, network, item.entity_id, score=item.score)
            for item in ranked
        ]


class LinkExplainer:
    """Attribute a predicted link to endpoint feature similarities."""

    def __init__(self, model: LinkPredictionModel) -> None:
        self.model = model

    def explain_link(
        self,
        tensors: GraphTensors,
        network: SignalingNetwork,
        source_id: str,
        target_id: str,
    ) -> Dict[str, Any]:
        if self.model.head is None:
            raise RuntimeError("Link model is not fitted")
        score = self.model.score_pair(tensors, source_id, target_id)
        i = tensors.row_of(source_id)
        j = tensors.row_of(target_id)
        # Feature agreement: products of aligned channels (gradient×input proxy)
        contrib = []
        for k, name in enumerate(tensors.node_feature_names):
            c = tensors.x[i][k] * tensors.x[j][k]
            contrib.append({"feature": name, "product": c})
        contrib.sort(key=lambda d: abs(d["product"]), reverse=True)
        structural = build_structural_rationale(network, tensors, source_id)
        return {
            "source_id": source_id,
            "target_id": target_id,
            "source_name": network.registry.get(source_id).name,
            "target_name": network.registry.get(target_id).name,
            "score": score,
            "top_feature_products": contrib[:8],
            "shared_cluster": structural.cluster_ids.get(source_id)
            == structural.cluster_ids.get(target_id),
            "structural_notes": structural.notes,
        }


class AIScientistReasoner:
    """
    End-to-end: rank targets, explain top hits, optionally surface crosstalk.
    """

    def __init__(
        self,
        target_model: TargetDiscoveryModel,
        *,
        link_model: Optional[LinkPredictionModel] = None,
    ) -> None:
        self.target_model = target_model
        self.link_model = link_model
        self.explainer = GraphExplainer(target_model)

    def recommend(
        self,
        tensors: GraphTensors,
        network: SignalingNetwork,
        *,
        top_k: int = 3,
        include_links: bool = True,
        link_top_k: int = 5,
    ) -> Dict[str, Any]:
        explanations = self.explainer.explain_top_targets(
            tensors, network, top_k=top_k
        )
        links: List[Dict[str, Any]] = []
        if include_links and self.link_model is not None and self.link_model.head is not None:
            for ls in self.link_model.suggest(tensors, network, top_k=link_top_k):
                links.append(ls.as_dict())
        return {
            "recommendations": [e.as_dict() for e in explanations],
            "suggested_crosstalk": links,
            "n_nodes": tensors.num_nodes,
            "n_edges": tensors.num_edges,
        }
