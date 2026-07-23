"""
Domain 12 — Causal BioReasoner NLP engine.

Extracts top-k causal signaling cascades via Dijkstra search over
``d = −log(α + ε)`` attention distances and emits a deterministic
``CausalContextPayload`` plus a template-grounded discovery-brief prompt.
"""

from __future__ import annotations

from heapq import heappop, heappush
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple
import math
import time

from cistron.ai.prioritizer import (
    NodeFeatureVector,
    PrioritizationResult,
    prioritize,
)
from cistron.models.graph import CausalActivityGraph, MechanismKind
from cistron.models.reasoner import CausalContextPayload, CausalPathContext
from cistron.models.serialization import ScrubberPayload
from cistron.serialization.scrubber import edge_flux_key

DISTANCE_EPS = 1e-6
DISCOVERY_BRIEF_RULES = (
    "Describe the causal activation cascade strictly using the provided "
    "state deltas, mechanism tags, and time delays. Do not infer unlisted "
    "biological relationships or hallucinate pathways."
)


def attention_to_distance(alpha: float, *, eps: float = DISTANCE_EPS) -> float:
    """
    ``d = −log(α + ε)`` — high attention → short distance.

    Distances are clamped to ``≥ 0`` so that ``α ≈ 1`` (where ``α+ε > 1``)
    cannot produce negative weights that break Dijkstra on cyclic graphs.
    """
    a = max(0.0, min(1.0, float(alpha)))
    return float(max(0.0, -math.log(a + eps)))


def build_distance_graph(
    graph: CausalActivityGraph,
    attention_matrix: Mapping[str, float],
    *,
    eps: float = DISTANCE_EPS,
) -> Dict[str, List[Tuple[str, float, str]]]:
    """
    Adjacency list ``src → [(dst, distance, edge_key), …]`` from attention.
    """
    adj: Dict[str, List[Tuple[str, float, str]]] = {s: [] for s in graph.nodes}
    for edge in graph.edges:
        key = edge_flux_key(edge.source, edge.target)
        alpha = float(attention_matrix.get(key, 0.0))
        dist = attention_to_distance(alpha, eps=eps)
        adj.setdefault(edge.source, []).append((edge.target, dist, key))
        adj.setdefault(edge.target, [])
    return adj


def _dijkstra(
    adj: Mapping[str, Sequence[Tuple[str, float, str]]],
    source: str,
    target: str,
    *,
    banned_nodes: Optional[Set[str]] = None,
    banned_edges: Optional[Set[Tuple[str, str]]] = None,
) -> Optional[Tuple[List[str], float]]:
    """
    Classical Dijkstra; returns ``(node_path, total_distance)`` or ``None``.
    """
    banned_nodes = banned_nodes or set()
    banned_edges = banned_edges or set()
    if source in banned_nodes or target in banned_nodes:
        return None
    if source not in adj or target not in adj:
        return None

    dist: Dict[str, float] = {source: 0.0}
    prev: Dict[str, Optional[str]] = {source: None}
    heap: List[Tuple[float, str]] = [(0.0, source)]
    seen: Set[str] = set()

    while heap:
        d_u, u = heappop(heap)
        if u in seen:
            continue
        seen.add(u)
        if u == target:
            break
        for v, w, _key in adj.get(u, ()):
            if v in banned_nodes or (u, v) in banned_edges:
                continue
            nd = d_u + w
            if nd < dist.get(v, math.inf):
                dist[v] = nd
                prev[v] = u
                heappush(heap, (nd, v))

    if target not in dist:
        return None

    # Reconstruct
    path: List[str] = []
    cur: Optional[str] = target
    while cur is not None:
        path.append(cur)
        cur = prev.get(cur)
    path.reverse()
    if not path or path[0] != source:
        return None
    return path, float(dist[target])


def _yen_k_shortest(
    adj: Mapping[str, Sequence[Tuple[str, float, str]]],
    source: str,
    target: str,
    k: int,
) -> List[Tuple[List[str], float]]:
    """Yen's loopless k-shortest paths over the attention-distance graph."""
    if k < 1:
        return []
    first = _dijkstra(adj, source, target)
    if first is None:
        return []

    A: List[Tuple[List[str], float]] = [first]
    B: List[Tuple[float, int, List[str]]] = []  # (dist, tie, path)
    tie = 0

    for _ in range(1, k):
        prev_path, _ = A[-1]
        for i in range(len(prev_path) - 1):
            spur = prev_path[i]
            root = prev_path[: i + 1]

            banned_edges: Set[Tuple[str, str]] = set()
            banned_nodes: Set[str] = set(root[:-1])
            for p, _d in A:
                if len(p) > i and p[: i + 1] == root:
                    banned_edges.add((p[i], p[i + 1]))

            spur_result = _dijkstra(
                adj,
                spur,
                target,
                banned_nodes=banned_nodes,
                banned_edges=banned_edges,
            )
            if spur_result is None:
                continue
            spur_path, spur_dist = spur_result
            # Root distance
            root_dist = 0.0
            ok = True
            for a, b in zip(root, root[1:]):
                edge_w = None
                for v, w, _ in adj.get(a, ()):
                    if v == b:
                        edge_w = w
                        break
                if edge_w is None:
                    ok = False
                    break
                root_dist += edge_w
            if not ok:
                continue
            total_path = root[:-1] + spur_path
            # Reject cycles
            if len(total_path) != len(set(total_path)):
                continue
            total_dist = root_dist + spur_dist
            # Deduplicate against A and B
            if any(total_path == p for p, _ in A):
                continue
            if any(total_path == p for _, __, p in B):
                continue
            heappush(B, (total_dist, tie, total_path))
            tie += 1

        if not B:
            break
        d_next, _, path_next = heappop(B)
        A.append((path_next, float(d_next)))

    return A


def extract_causal_paths(
    graph: CausalActivityGraph,
    prioritization_result: PrioritizationResult,
    source_node: str,
    target_node: str,
    k: int = 3,
    *,
    eps: float = DISTANCE_EPS,
) -> List[List[str]]:
    """
    Top-k highest-throughput cascades ``N1 → … → Nm`` via Dijkstra / Yen
    over ``d = −log(α + ε)``.
    """
    src = source_node.strip()
    tgt = target_node.strip()
    adj = build_distance_graph(
        graph, prioritization_result.attention_matrix, eps=eps
    )
    ranked = _yen_k_shortest(adj, src, tgt, k=max(1, int(k)))
    return [path for path, _dist in ranked]


def extract_causal_paths_timed(
    graph: CausalActivityGraph,
    prioritization_result: PrioritizationResult,
    source_node: str,
    target_node: str,
    k: int = 3,
    *,
    eps: float = DISTANCE_EPS,
) -> Tuple[List[List[str]], float]:
    """Same as :func:`extract_causal_paths`, also returning elapsed seconds."""
    t0 = time.perf_counter()
    paths = extract_causal_paths(
        graph,
        prioritization_result,
        source_node,
        target_node,
        k=k,
        eps=eps,
    )
    return paths, time.perf_counter() - t0


def _edge_lookup(graph: CausalActivityGraph) -> Dict[Tuple[str, str], Any]:
    return {(e.source, e.target): e for e in graph.edges}


def _path_context(
    nodes: Sequence[str],
    *,
    graph: CausalActivityGraph,
    prioritization: PrioritizationResult,
    path_distance: float,
) -> CausalPathContext:
    edges = _edge_lookup(graph)
    state_deltas: Dict[str, float] = {}
    latencies: Dict[str, float] = {}
    for n in nodes:
        vec = prioritization.node_vectors.get(n)
        state_deltas[n] = float(vec.delta_y) if vec is not None else 0.0
        if n in graph.nodes:
            latencies[n] = float(graph.nodes[n].tau_min)

    mechanisms: List[str] = []
    signs: List[int] = []
    attentions: List[float] = []
    cum = 1.0
    for a, b in zip(nodes, nodes[1:]):
        e = edges.get((a, b))
        if e is None:
            mechanisms.append("unknown")
            signs.append(0)
            attentions.append(0.0)
            cum = 0.0
            continue
        mech = e.mechanism.value if isinstance(e.mechanism, MechanismKind) else str(e.mechanism)
        mechanisms.append(mech)
        signs.append(int(e.sign))
        key = edge_flux_key(a, b)
        alpha = float(prioritization.attention_matrix.get(key, 0.0))
        attentions.append(alpha)
        cum *= alpha

    return CausalPathContext(
        nodes=list(nodes),
        state_deltas=state_deltas,
        cumulative_attention=float(cum),
        mechanisms=mechanisms,
        path_distance=float(path_distance),
        edge_attentions=attentions,
        latencies_min=latencies,
        signs=signs,
    )


def _perturbed_nodes(
    graph: CausalActivityGraph,
    payload: ScrubberPayload,
    prioritization: PrioritizationResult,
) -> List[str]:
    perturbed: Set[str] = set()
    meta = payload.metadata or {}
    engine = meta.get("engine") if isinstance(meta.get("engine"), Mapping) else {}
    for k in (engine or {}).get("knockouts") or meta.get("knockouts") or []:
        perturbed.add(str(k))
    clamped = (engine or {}).get("clamped") or {}
    if isinstance(clamped, Mapping):
        for sym in clamped:
            perturbed.add(str(sym))
    for sym, vec in prioritization.node_vectors.items():
        if vec.is_knocked_out:
            perturbed.add(sym)
    # Stable order
    return sorted(s for s in perturbed if s in graph.nodes or s in prioritization.node_vectors)


def build_causal_context(
    graph: CausalActivityGraph,
    payload: ScrubberPayload,
    *,
    source_node: str,
    target_node: str,
    k: int = 3,
    prioritization: Optional[PrioritizationResult] = None,
) -> CausalContextPayload:
    """
    Run prioritization (if needed), extract top-k paths, and pack a
    deterministic :class:`CausalContextPayload`.
    """
    prio = prioritization or prioritize(graph, payload)
    adj = build_distance_graph(graph, prio.attention_matrix)
    ranked = _yen_k_shortest(adj, source_node.strip(), target_node.strip(), k=max(1, int(k)))

    paths = [
        _path_context(path, graph=graph, prioritization=prio, path_distance=dist)
        for path, dist in ranked
    ]

    top_mr = ""
    if prio.master_regulators:
        top_mr = str(prio.master_regulators[0][0])

    return CausalContextPayload(
        simulation_id=payload.simulation_id,
        extracted_paths=paths,
        top_master_regulator=top_mr,
        perturbed_nodes=_perturbed_nodes(graph, payload, prio),
        source_node=source_node.strip(),
        target_node=target_node.strip(),
        metadata={
            "graph_name": graph.name,
            "k": int(k),
            "n_paths": len(paths),
            "distance_eps": DISTANCE_EPS,
        },
    )


def generate_discovery_brief_prompt(context_payload: CausalContextPayload) -> str:
    """
    Template-grounded LLM prompt: narrative must stay inside the payload facts.
    """
    lines: List[str] = [
        "SYSTEM ROLE: Causal BioReasoner discovery-brief synthesizer.",
        f"RULES: {DISCOVERY_BRIEF_RULES}",
        "",
        f"simulation_id: {context_payload.simulation_id}",
        f"top_master_regulator: {context_payload.top_master_regulator or '(none)'}",
        f"perturbed_nodes: {', '.join(context_payload.perturbed_nodes) or '(none)'}",
        f"query_path: {context_payload.source_node or '?'} -> {context_payload.target_node or '?'}",
        "",
        "EXTRACTED_CAUSAL_PATHS:",
    ]

    if not context_payload.extracted_paths:
        lines.append("  (no path found — state that no cascade was recovered)")
    else:
        for idx, path in enumerate(context_payload.extracted_paths, start=1):
            chain = " -> ".join(path.nodes)
            lines.append(f"  PATH {idx}: {chain}")
            lines.append(f"    cumulative_attention: {path.cumulative_attention:.6g}")
            lines.append(f"    path_distance: {path.path_distance:.6g}")
            lines.append(f"    mechanisms: {path.mechanisms}")
            lines.append(f"    signs: {path.signs}")
            delta_bits = ", ".join(
                f"{n}: Δy={path.state_deltas.get(n, 0.0):+.4f}"
                f" (τ={path.latencies_min.get(n, float('nan')):g} min)"
                for n in path.nodes
            )
            lines.append(f"    state_deltas: {delta_bits}")

    lines.extend(
        [
            "",
            "TASK: Write a concise discovery brief (≤180 words) that only cites",
            "nodes, Δy values, mechanisms, and τ values listed above.",
            "If a relationship is not in EXTRACTED_CAUSAL_PATHS, omit it.",
        ]
    )
    return "\n".join(lines)


def synthesize_deterministic_brief(context_payload: CausalContextPayload) -> str:
    """
    Hallucination-free template narrative (no LLM). Safe default for CI / UI.
    """
    if not context_payload.extracted_paths:
        return (
            f"Simulation {context_payload.simulation_id}: no causal path recovered "
            f"from {context_payload.source_node} to {context_payload.target_node}."
        )

    primary = context_payload.extracted_paths[0]
    hops: List[str] = []
    for i, (a, b) in enumerate(zip(primary.nodes, primary.nodes[1:])):
        mech = primary.mechanisms[i] if i < len(primary.mechanisms) else "unknown"
        sign = primary.signs[i] if i < len(primary.signs) else 0
        arrow = "inhibits" if sign < 0 else "stimulates"
        da = primary.state_deltas.get(a, 0.0)
        db = primary.state_deltas.get(b, 0.0)
        ta = primary.latencies_min.get(a)
        tb = primary.latencies_min.get(b)
        hops.append(
            f"{a} (Δy={da:+.3f}, τ={ta:g} min) {arrow} {b} "
            f"(Δy={db:+.3f}, τ={tb:g} min) via {mech}"
        )

    mr = context_payload.top_master_regulator or "n/a"
    pert = ", ".join(context_payload.perturbed_nodes) or "none"
    body = "; ".join(hops)
    return (
        f"Discovery brief [{context_payload.simulation_id}]: "
        f"primary cascade {' → '.join(primary.nodes)} "
        f"(cumulative attention={primary.cumulative_attention:.4f}). "
        f"{body}. "
        f"Top master regulator={mr}; perturbed nodes={pert}."
    )


__all__ = [
    "DISCOVERY_BRIEF_RULES",
    "DISTANCE_EPS",
    "CausalContextPayload",
    "CausalPathContext",
    "attention_to_distance",
    "build_causal_context",
    "build_distance_graph",
    "extract_causal_paths",
    "extract_causal_paths_timed",
    "generate_discovery_brief_prompt",
    "synthesize_deterministic_brief",
]
