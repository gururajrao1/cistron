"""
Sub-20 ms AI Scientist live reasoning synthesizer.

Triggered on every laboratory filter change to explain mechanistic cause →
effect shifts via trajectory deltas, flux displacement, and GAT attention
re-routing — without calling an external LLM.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
import time

from voidsignal.models.prioritization import PrioritizationResult
from voidsignal.models.serialization import ScrubberPayload
from voidsignal.models.xai import PreviousStateSummary, ScientistReasoning


def _mean(xs: Sequence[float]) -> float:
    return float(sum(xs) / len(xs)) if xs else 0.0


def _top_deltas(
    curr: Mapping[str, float],
    prev: Mapping[str, float],
    *,
    k: int = 5,
) -> Dict[str, float]:
    keys = set(curr) | set(prev)
    deltas = {n: float(curr.get(n, 0.0) - prev.get(n, 0.0)) for n in keys}
    ranked = sorted(deltas.items(), key=lambda p: (-abs(p[1]), p[0]))
    return {n: d for n, d in ranked[:k] if abs(d) > 1e-6}


def _attention_reroutes(
    curr: Mapping[str, float],
    prev: Mapping[str, float],
    *,
    k: int = 4,
) -> Dict[str, float]:
    keys = set(curr) | set(prev)
    deltas = {e: float(curr.get(e, 0.0) - prev.get(e, 0.0)) for e in keys}
    ranked = sorted(deltas.items(), key=lambda p: (-abs(p[1]), p[0]))
    return {e: d for e, d in ranked[:k] if abs(d) > 1e-5}


def _final_states(payload: ScrubberPayload) -> Dict[str, float]:
    return {
        sym: float(series[-1]) if series else 0.0
        for sym, series in payload.nodes.items()
    }


def _edge_means(payload: ScrubberPayload) -> Dict[str, float]:
    return {
        key: _mean(series)
        for key, series in payload.edges.items()
    }


def _describe_perturbation(delta: Optional[Mapping[str, Any]]) -> str:
    if not delta:
        return "baseline condition resolve"
    parts: List[str] = []
    if delta.get("condition_query"):
        parts.append(f"condition «{delta['condition_query']}»")
    kos = delta.get("knockouts") or delta.get("custom_knockouts")
    if kos:
        parts.append(f"knockout {', '.join(str(k) for k in kos)}")
    clamps = delta.get("clamps") or delta.get("custom_clamps")
    if isinstance(clamps, Mapping) and clamps:
        cbits = [f"{k}={float(v):.2f}" for k, v in list(clamps.items())[:3]]
        parts.append("clamp " + ", ".join(cbits))
    drugs = delta.get("drugs") or delta.get("drug_perturbations")
    if drugs:
        d0 = drugs[0] if isinstance(drugs, list) else drugs
        if isinstance(d0, Mapping):
            tgt = d0.get("target", "?")
            c = d0.get("c_drug", d0.get("concentration", "?"))
            parts.append(f"drug {tgt} C={c}")
    return "; ".join(parts) if parts else "filter adjustment"


def _sentiment(total_flux_delta: float, node_deltas: Mapping[str, float]) -> str:
    if abs(total_flux_delta) < 1e-4 and not node_deltas:
        return "neutral"
    ups = sum(1 for v in node_deltas.values() if v > 0)
    downs = sum(1 for v in node_deltas.values() if v < 0)
    if ups and downs:
        return "mixed"
    if total_flux_delta > 1e-4 or (ups and not downs):
        return "up"
    if total_flux_delta < -1e-4 or (downs and not ups):
        return "down"
    return "neutral"


def generate_scientist_reasoning(
    prev_state: Optional[PreviousStateSummary | Mapping[str, Any]],
    curr_state: ScrubberPayload | Mapping[str, Any],
    perturbation_delta: Optional[Mapping[str, Any]] = None,
    *,
    prioritization: Optional[PrioritizationResult] = None,
) -> ScientistReasoning:
    """
    Synthesize a crisp 2–3 sentence mechanistic brief in <20 ms.

    Parameters
    ----------
    prev_state
        Prior simulation snapshot (node finals / attention) or ``None`` on
        first run.
    curr_state
        Current :class:`ScrubberPayload` (or a dict with ``nodes`` / ``edges``).
    perturbation_delta
        Human-readable filter change (knockouts, clamps, drugs, query).
    prioritization
        Optional current GAT result for attention-aware phrasing.
    """
    t0 = time.perf_counter()

    # Normalize previous
    if prev_state is None:
        prev = PreviousStateSummary()
    elif isinstance(prev_state, PreviousStateSummary):
        prev = prev_state
    else:
        prev = PreviousStateSummary.model_validate(prev_state)

    # Normalize current payload-like
    if isinstance(curr_state, ScrubberPayload):
        curr_finals = _final_states(curr_state)
        curr_flux = _edge_means(curr_state)
        sim_id = curr_state.simulation_id
    else:
        nodes = curr_state.get("nodes") or {}
        edges = curr_state.get("edges") or {}
        curr_finals = {
            k: float(v[-1] if isinstance(v, (list, tuple)) and v else v)
            for k, v in nodes.items()
        }
        curr_flux = {
            k: _mean(v) if isinstance(v, (list, tuple)) else float(v)
            for k, v in edges.items()
        }
        sim_id = str(curr_state.get("simulation_id") or "")

    curr_attention: Dict[str, float] = {}
    if prioritization is not None:
        curr_attention = dict(prioritization.attention_matrix)
    elif isinstance(curr_state, Mapping) and curr_state.get("attention_matrix"):
        curr_attention = {
            str(k): float(v) for k, v in curr_state["attention_matrix"].items()
        }

    node_deltas = _top_deltas(curr_finals, prev.node_finals, k=5)
    attn_deltas = _attention_reroutes(curr_attention, prev.attention_matrix, k=4)

    prev_flux_sum = sum(prev.edge_mean_flux.values()) if prev.edge_mean_flux else 0.0
    curr_flux_sum = sum(curr_flux.values())
    # If no previous flux recorded, use node-activity proxy displacement
    if not prev.edge_mean_flux and prev.node_finals:
        prev_flux_sum = sum(prev.node_finals.values())
        curr_flux_sum = sum(curr_finals.values())
    total_flux_delta = float(curr_flux_sum - prev_flux_sum)

    pert = _describe_perturbation(perturbation_delta)
    top_regs: List[Tuple[str, float]] = []
    if prioritization is not None and prioritization.master_regulators:
        top_regs = list(prioritization.master_regulators[:3])

    # Sentence 1 — perturbation cause
    if not prev.node_finals:
        s1 = (
            f"Resolved {pert}: the Hill-cube network settled with "
            f"Σy₆₀={sum(curr_finals.values()):.2f} across {len(curr_finals)} nodes."
        )
    else:
        s1 = f"After {pert}, total pathway flux displaced by ΔF={total_flux_delta:+.3f}."

    # Sentence 2 — node trajectory shifts
    if node_deltas:
        bits = [f"{n} {d:+.3f}" for n, d in list(node_deltas.items())[:3]]
        s2 = f"Largest activity shifts (Δy₆₀): {', '.join(bits)}."
    elif top_regs:
        bits = [f"{n} (S={s:.3f})" for n, s in top_regs[:2]]
        s2 = f"Dominant attentive drivers: {', '.join(bits)}."
    else:
        s2 = "Node trajectories remain near the prior steady state."

    # Sentence 3 — attention re-routing / mechanism
    if attn_deltas:
        edge, da = next(iter(attn_deltas.items()))
        direction = "strengthened" if da > 0 else "weakened"
        s3 = (
            f"GAT attention re-routed: {edge} {direction} "
            f"(Δα={da:+.3f}), redirecting causal flow through the cascade."
        )
    elif top_regs:
        driver = top_regs[0][0]
        s3 = (
            f"Causal pressure concentrates on {driver}, marking it as the "
            f"primary lever for downstream readout control."
        )
    else:
        s3 = "Attentive flow topology is unchanged relative to the previous filter state."

    brief = " ".join([s1, s2, s3])
    sentiment = _sentiment(total_flux_delta, node_deltas)

    return ScientistReasoning(
        brief=brief,
        sentiment=sentiment,
        total_flux_delta=total_flux_delta,
        top_node_deltas=node_deltas,
        attention_reroutes=attn_deltas,
        perturbation_summary=pert,
        elapsed_ms=(time.perf_counter() - t0) * 1000.0,
        metadata={
            "simulation_id": sim_id,
            "n_nodes": len(curr_finals),
            "had_previous": bool(prev.node_finals),
        },
    )


def snapshot_state_summary(
    payload: ScrubberPayload,
    prioritization: PrioritizationResult,
    *,
    knockouts: Optional[Sequence[str]] = None,
    clamps: Optional[Mapping[str, float]] = None,
    condition_query: Optional[str] = None,
    scientist_brief: Optional[str] = None,
) -> PreviousStateSummary:
    """Build a compact previous-state snapshot for the next filter delta."""
    return PreviousStateSummary(
        node_finals=_final_states(payload),
        attention_matrix=dict(prioritization.attention_matrix),
        edge_mean_flux=_edge_means(payload),
        knockouts=list(knockouts or []),
        clamps={k: float(v) for k, v in (clamps or {}).items()},
        condition_query=condition_query,
        scientist_brief=scientist_brief,
    )


__all__ = [
    "generate_scientist_reasoning",
    "snapshot_state_summary",
]
