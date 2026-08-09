"""Disease-context 'what if this protein changes' explainers for any pathway disease."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence
import logging

from cistron.api.biomed_llm import generate_disease_impact_narrative

logger = logging.getLogger(__name__)


def build_disease_impact(
    symbol: str,
    meta: Dict[str, Any],
    *,
    condition_query: str = "",
    upstream: Optional[Sequence[str]] = None,
    downstream: Optional[Sequence[str]] = None,
    delta_y: Optional[float] = None,
    use_llm: bool = True,
) -> Dict[str, str]:
    """
    Explain how activity / interaction / structure changes in ``symbol``
    could matter in the *current* disease pathway — not only hypoxia.
    """
    sym = symbol.strip().upper() or symbol
    disease = (condition_query or "").strip() or "this pathway disease"
    up = [u for u in (upstream or []) if u]
    down = [d for d in (downstream or []) if d]
    n_up, n_down = len(up), len(down)
    hubby = (n_up + n_down) >= 4

    role = "connector"
    if n_down >= 3 and n_up <= 1:
        role = "driver-like"
    elif n_up >= 3 and n_down <= 1:
        role = "sensor/integrator"
    elif n_down == 0 and n_up == 0:
        role = "isolated"

    if_up = (
        f"If {sym} activity goes **up** in «{disease}», signals tend to push harder into "
    )
    if down:
        if_up += f"{', '.join(down[:4])}" + ("…" if n_down > 4 else "") + ". "
    else:
        if_up += "its downstream partners (none listed in this graph slice). "
    if hubby:
        if_up += "Because it sits on many edges, small increases can ripple across the network. "
    if_up += "In the Studio, try Clamp expression near 1.0 and re-run to see Δy and fluxes move."

    if_down = (
        f"If {sym} is reduced or knocked out in «{disease}», inputs from "
    )
    if up:
        if_down += f"{', '.join(up[:4])}" + ("…" if n_up > 4 else "")
    else:
        if_down += "upstream partners"
    if_down += " have less of a foothold, and "
    if down:
        if_down += f"{', '.join(down[:3])} may quiet down. "
    else:
        if_down += "downstream activity may drop. "
    if_down += "Use Knockout (wᵢ=0) in the inspector to simulate loss-of-function."

    if role == "driver-like":
        structure = (
            f"Structure / interaction changes in {sym} (mutation, drug binding, PTM) often act like "
            f"rewiring a hub switch in «{disease}»: the same neighbors stay connected, but the "
            f"strength of outgoing edges changes — which is what our Hill-cube weights approximate."
        )
    elif role == "sensor/integrator":
        structure = (
            f"{sym} looks more like a listener in «{disease}». Altering how it binds upstream partners "
            f"can blunt or amplify the message before it reaches the rest of the cascade."
        )
    elif role == "isolated":
        structure = (
            f"This graph slice doesn’t show neighbors for {sym} yet. Build the disease pathway "
            f"(Pathways → Apply → Studio) so interaction changes have edges to act on."
        )
    else:
        structure = (
            f"In «{disease}», {sym} is a mid-path connector. Changing its fold, binding surfaces, "
            f"or interaction partners can retune both incoming and outgoing fluxes — "
            f"similar in spirit to how hypoxia rewires EGLN1↔HIF1A, but for *this* disease map."
        )

    sim_note = ""
    if delta_y is not None and abs(float(delta_y)) >= 0.05:
        direction = "increased" if float(delta_y) > 0 else "decreased"
        sim_note = (
            f" Latest simulation already shows {sym} activity {direction} "
            f"(Δy={float(delta_y):+.2f}) under «{disease}»."
        )

    overview = (
        f"For «{disease}», {sym} is classified as a {role} node "
        f"({n_up} upstream · {n_down} downstream).{sim_note} "
        f"Hypoxia is just one scenario we ship as a preset — any Reactome/STRING disease "
        f"you build in Pathways gets the same style of impact reading."
    )

    impact = {
        "overview": overview,
        "if_activity_up": if_up.replace("**", ""),
        "if_activity_down": if_down.replace("**", ""),
        "structure_or_interaction": structure,
        "mode": "template",
    }

    # LLM polish only when a real disease/pathway query is active (avoids a second
    # HF call on bare gene clicks with no Pathways context).
    has_disease = bool((condition_query or "").strip())
    if use_llm and has_disease:
        try:
            llm = generate_disease_impact_narrative(
                meta,
                condition_query=condition_query.strip(),
                upstream=up,
                downstream=down,
                delta_y=delta_y,
                role=role,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("disease impact LLM failed: %s", exc)
            llm = None
        if llm:
            for key in ("overview", "if_activity_up", "if_activity_down", "structure_or_interaction"):
                if llm.get(key):
                    impact[key] = str(llm[key])
            impact["mode"] = str(llm.get("mode") or "hf_llm")

    return impact
