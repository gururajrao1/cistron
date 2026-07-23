"""
Topological vulnerability & synthetic lethality analysis.

Operates on :class:`CausalActivityGraph` adjacency to score bottlenecks
(betweenness, hub degree, flow PageRank), detect signed feedback cycles, and
evaluate pairwise virtual knockouts for synthetic lethality.
"""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple
import time

import numpy as np

from cistron.ai.prioritizer import (
    ATTENTION_EPS,
    _payload_clamps,
    _payload_knockouts,
    _simulate_knockout_payload,
    output_sum_at_final,
    resolve_output_nodes,
)
from cistron.models.graph import CausalActivityGraph
from cistron.models.serialization import ScrubberPayload
from cistron.models.topology_analysis import (
    BottleneckNode,
    FeedbackLoop,
    SyntheticLethalPair,
    TopologicalAnalysis,
)

EdgeKey = Tuple[str, str]


def _adjacency(
    graph: CausalActivityGraph,
) -> Tuple[List[str], Dict[str, List[str]], Dict[EdgeKey, int]]:
    nodes = sorted(graph.nodes.keys())
    succ: Dict[str, List[str]] = {n: [] for n in nodes}
    signs: Dict[EdgeKey, int] = {}
    for e in graph.edges:
        if e.source not in succ:
            succ[e.source] = []
        if e.target not in succ:
            succ[e.target] = []
        succ[e.source].append(e.target)
        signs[(e.source, e.target)] = int(e.sign)
    # Deduplicate adjacency lists
    for n in list(succ.keys()):
        succ[n] = sorted(set(succ[n]))
    nodes = sorted(set(nodes) | set(succ.keys()))
    for n in nodes:
        succ.setdefault(n, [])
    return nodes, succ, signs


def hub_degree_scores(succ: Mapping[str, Sequence[str]], nodes: Sequence[str]) -> Dict[str, float]:
    """Normalized total degree (in + out)."""
    indeg: Dict[str, int] = {n: 0 for n in nodes}
    outdeg: Dict[str, int] = {n: len(succ.get(n, [])) for n in nodes}
    for u in nodes:
        for v in succ.get(u, []):
            indeg[v] = indeg.get(v, 0) + 1
            indeg.setdefault(u, indeg.get(u, 0))
    raw = {n: float(indeg.get(n, 0) + outdeg.get(n, 0)) for n in nodes}
    mx = max(raw.values()) if raw else 1.0
    if mx <= 0:
        return {n: 0.0 for n in nodes}
    return {n: raw[n] / mx for n in nodes}


def betweenness_centrality(
    succ: Mapping[str, Sequence[str]],
    nodes: Sequence[str],
) -> Dict[str, float]:
    """Brandes betweenness centrality (directed), normalized to [0, 1]."""
    n = len(nodes)
    if n <= 2:
        return {node: 0.0 for node in nodes}
    cb = {node: 0.0 for node in nodes}
    for s in nodes:
        stack: List[str] = []
        pred: Dict[str, List[str]] = {w: [] for w in nodes}
        sigma = {w: 0.0 for w in nodes}
        dist = {w: -1 for w in nodes}
        sigma[s] = 1.0
        dist[s] = 0
        queue = [s]
        qi = 0
        while qi < len(queue):
            v = queue[qi]
            qi += 1
            stack.append(v)
            for w in succ.get(v, []):
                if dist[w] < 0:
                    queue.append(w)
                    dist[w] = dist[v] + 1
                if dist[w] == dist[v] + 1:
                    sigma[w] += sigma[v]
                    pred[w].append(v)
        delta = {w: 0.0 for w in nodes}
        while stack:
            w = stack.pop()
            for v in pred[w]:
                if sigma[w] > 0:
                    delta[v] += (sigma[v] / sigma[w]) * (1.0 + delta[w])
            if w != s:
                cb[w] += delta[w]
    # Normalize by (n-1)(n-2) for directed graphs
    norm = float((n - 1) * (n - 2))
    if norm <= 0:
        return cb
    return {k: float(v / norm) for k, v in cb.items()}


def flow_pagerank(
    succ: Mapping[str, Sequence[str]],
    nodes: Sequence[str],
    *,
    damping: float = 0.85,
    iters: int = 40,
) -> Dict[str, float]:
    """Directed PageRank as a flow-importance proxy."""
    n = len(nodes)
    if n == 0:
        return {}
    index = {node: i for i, node in enumerate(nodes)}
    # Column-stochastic transition: M[j,i] = 1/outdeg(i) if i→j
    M = np.zeros((n, n), dtype=float)
    for u in nodes:
        outs = [v for v in succ.get(u, []) if v in index]
        if not outs:
            # Dangling → uniform
            M[:, index[u]] = 1.0 / n
            continue
        p = 1.0 / len(outs)
        for v in outs:
            M[index[v], index[u]] += p
    pr = np.full(n, 1.0 / n, dtype=float)
    teleport = np.full(n, 1.0 / n, dtype=float)
    for _ in range(iters):
        pr = damping * (M @ pr) + (1.0 - damping) * teleport
    mx = float(pr.max()) if pr.size else 1.0
    if mx <= 0:
        mx = 1.0
    return {nodes[i]: float(pr[i] / mx) for i in range(n)}


def detect_feedback_loops(
    succ: Mapping[str, Sequence[str]],
    signs: Mapping[EdgeKey, int],
    nodes: Sequence[str],
    *,
    max_cycle_len: int = 6,
    max_cycles: int = 12,
) -> List[FeedbackLoop]:
    """
    Enumerate simple directed cycles (length ≥ 2) and classify by sign product.

    Negative feedback: product of edge signs = −1
    Positive feedback: product = +1
    """
    cycles: List[FeedbackLoop] = []
    seen: Set[Tuple[str, ...]] = set()

    def _canonical(path: List[str]) -> Tuple[str, ...]:
        # Rotate so the lexicographically smallest node is first
        if not path:
            return tuple()
        k = min(range(len(path)), key=lambda i: path[i])
        rot = path[k:] + path[:k]
        return tuple(rot)

    def dfs(start: str, u: str, path: List[str], used: Set[str]) -> None:
        if len(cycles) >= max_cycles:
            return
        if len(path) > max_cycle_len:
            return
        for v in succ.get(u, []):
            if v == start and len(path) >= 2:
                canon = _canonical(path)
                if canon in seen:
                    continue
                seen.add(canon)
                # Sign product around the cycle
                prod = 1
                seq = path + [start]
                for i in range(len(path)):
                    prod *= int(signs.get((seq[i], seq[i + 1]), 1))
                if prod < 0:
                    ctype = "Negative Feedback"
                elif prod > 0:
                    ctype = "Positive Feedback"
                else:
                    ctype = "Mixed Feedback"
                cycles.append(
                    FeedbackLoop(
                        cycle=list(canon),
                        type=ctype,
                        length=len(canon),
                        sign_product=int(np.sign(prod) or 1),
                    )
                )
                continue
            if v in used or v < start:
                # v < start prunes duplicate cycle starts
                continue
            used.add(v)
            path.append(v)
            dfs(start, v, path, used)
            path.pop()
            used.remove(v)

    for s in nodes:
        dfs(s, s, [s], {s})
        if len(cycles) >= max_cycles:
            break

    cycles.sort(key=lambda c: (c.length, c.cycle[0] if c.cycle else ""))
    return cycles[:max_cycles]


def _role_for_scores(bc: float, hub: float, pr: float) -> str:
    if bc >= 0.45 and hub >= 0.5:
        return "Primary Signaling Bottleneck"
    if bc >= 0.35:
        return "Betweenness Bottleneck"
    if hub >= 0.7:
        return "Hub Connector"
    if pr >= 0.7:
        return "Flow Authority"
    return "Secondary Choke-Point"


def evaluate_synthetic_lethality(
    graph: CausalActivityGraph,
    payload: ScrubberPayload,
    *,
    candidate_nodes: Optional[Sequence[str]] = None,
    output_nodes: Optional[Sequence[str]] = None,
    output_collapse_threshold: float = 0.1,
    max_candidates: int = 5,
    t_end: float = 60.0,
    dense_output_points: int = 9,
    time_budget_ms: float = 350.0,
) -> List[SyntheticLethalPair]:
    """
    Pairwise virtual knockouts: SL when singles preserve output but dual
    collapses Σ y_output below ``output_collapse_threshold``.

    Uses a coarse ODE grid and a wall-clock budget so the search-and-simulate
    hot path stays interactive.
    """
    t0 = time.perf_counter()
    outputs = resolve_output_nodes(graph, output_nodes=output_nodes)
    clamps = _payload_clamps(payload)
    base_kos = _payload_knockouts(payload)
    y0 = output_sum_at_final(payload, outputs)

    if candidate_nodes is None:
        skip = set(clamps.keys()) | set(outputs) | set(base_kos)
        cand = [s for s in sorted(graph.nodes.keys()) if s not in skip]
        if len(cand) < 2:
            cand = [s for s in sorted(graph.nodes.keys()) if s not in base_kos]
    else:
        cand = [str(c) for c in candidate_nodes if c in graph.nodes]

    cand = cand[: max(2, max_candidates)]
    if len(cand) < 2:
        return []

    single_cache: Dict[str, float] = {}

    def _single(sym: str) -> float:
        if sym not in single_cache:
            p = _simulate_knockout_payload(
                graph,
                knockouts=[sym],
                clamps=clamps,
                t_end=t_end,
                base_knockouts=base_kos,
                dense_output_points=dense_output_points,
            )
            single_cache[sym] = output_sum_at_final(p, outputs)
        return single_cache[sym]

    pairs: List[SyntheticLethalPair] = []
    for a, b in combinations(cand, 2):
        if (time.perf_counter() - t0) * 1000.0 > time_budget_ms:
            break
        y_a = _single(a)
        y_b = _single(b)
        combo = _simulate_knockout_payload(
            graph,
            knockouts=[a, b],
            clamps=clamps,
            t_end=t_end,
            base_knockouts=base_kos,
            dense_output_points=dense_output_points,
        )
        y_ab = output_sum_at_final(combo, outputs)
        if y0 > ATTENTION_EPS:
            bliss = (y_a * y_b) / y0
        else:
            bliss = min(y_a, y_b)
        synergy = float(bliss - y_ab)

        # Synthetic lethality criterion
        singles_ok = y_a >= output_collapse_threshold and y_b >= output_collapse_threshold
        dual_collapse = y_ab < output_collapse_threshold
        strong_synergy = synergy > 0.05 and y_ab < 0.55 * max(y0, ATTENTION_EPS)

        if not ((singles_ok and dual_collapse) or strong_synergy):
            continue

        if dual_collapse and singles_ok:
            explanation = (
                f"Single KO of {a} or {b} preserves readout "
                f"(Σy={y_a:.2f}/{y_b:.2f}), but dual KO collapses output to {y_ab:.3f}."
            )
        else:
            explanation = (
                f"Dual pathway collapse: {a}+{b} synergy={synergy:.2f} "
                f"(baseline Σy={y0:.2f} → combo {y_ab:.2f})."
            )
        pairs.append(
            SyntheticLethalPair(
                pair=[a, b],
                synergy_score=float(max(0.0, min(1.0, synergy / max(y0, 1e-3)))),
                dual_output_sum=float(y_ab),
                single_a_output=float(y_a),
                single_b_output=float(y_b),
                baseline_output=float(y0),
                explanation=explanation,
            )
        )

    pairs.sort(key=lambda p: (-p.synergy_score, p.dual_output_sum, p.pair[0], p.pair[1]))
    return pairs


def analyze_topology_vulnerabilities(
    graph: CausalActivityGraph,
    *,
    payload: Optional[ScrubberPayload] = None,
    output_nodes: Optional[Sequence[str]] = None,
    top_bottlenecks: int = 5,
    max_sl_candidates: int = 5,
    run_synthetic_lethality: bool = False,
    t_end: float = 60.0,
    sl_time_budget_ms: float = 0.0,
) -> TopologicalAnalysis:
    """
    Full topological vulnerability pass on a causal activity graph.

    When ``payload`` is provided, pairwise synthetic lethality is evaluated on
    the highest-centrality non-output nodes (budgeted for interactive latency).
    """
    t0 = time.perf_counter()
    nodes, succ, signs = _adjacency(graph)
    bc = betweenness_centrality(succ, nodes)
    hub = hub_degree_scores(succ, nodes)
    pr = flow_pagerank(succ, nodes)

    ranked_nodes = sorted(
        nodes,
        key=lambda n: (-(0.5 * bc.get(n, 0.0) + 0.3 * hub.get(n, 0.0) + 0.2 * pr.get(n, 0.0)), n),
    )
    bottlenecks: List[BottleneckNode] = []
    for n in ranked_nodes[:top_bottlenecks]:
        score = 0.5 * bc[n] + 0.3 * hub[n] + 0.2 * pr[n]
        if score <= 0 and len(nodes) > 2:
            continue
        bottlenecks.append(
            BottleneckNode(
                node=n,
                betweenness=float(bc[n]),
                hub_degree=float(hub[n]),
                pagerank=float(pr[n]),
                role=_role_for_scores(bc[n], hub[n], pr[n]),
            )
        )

    loops = detect_feedback_loops(succ, signs, nodes)

    sl_pairs: List[SyntheticLethalPair] = []
    if run_synthetic_lethality and payload is not None and len(nodes) >= 2:
        outputs = set(resolve_output_nodes(graph, output_nodes=output_nodes))
        clamps = set(_payload_clamps(payload).keys())
        kos = set(_payload_knockouts(payload))
        candidates = [
            n
            for n in ranked_nodes
            if n not in outputs and n not in clamps and n not in kos
        ]
        if len(candidates) < 2:
            candidates = [n for n in ranked_nodes if n not in kos]
        remaining_ms = max(
            50.0,
            sl_time_budget_ms - (time.perf_counter() - t0) * 1000.0,
        )
        sl_pairs = evaluate_synthetic_lethality(
            graph,
            payload,
            candidate_nodes=candidates[:max_sl_candidates],
            output_nodes=output_nodes,
            t_end=t_end,
            dense_output_points=9,
            time_budget_ms=remaining_ms,
        )

    return TopologicalAnalysis(
        bottlenecks=bottlenecks,
        feedback_loops=loops,
        synthetic_lethal_pairs=sl_pairs[:8],
        elapsed_ms=(time.perf_counter() - t0) * 1000.0,
        metadata={
            "n_nodes": len(nodes),
            "n_edges": len(graph.edges),
            "method": "brandes_bc+pagerank+signed_cycles+pairwise_ko",
            "sl_budget_ms": sl_time_budget_ms,
        },
    )


__all__ = [
    "analyze_topology_vulnerabilities",
    "betweenness_centrality",
    "detect_feedback_loops",
    "evaluate_synthetic_lethality",
    "flow_pagerank",
    "hub_degree_scores",
]
