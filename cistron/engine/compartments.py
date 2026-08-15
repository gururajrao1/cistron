"""Server-side 2-compartment HIF1A translocation (cytoplasm ↔ nucleus).

Mass-action ODEs driven by the active graph O₂ / hypoxia trajectory::

    d[Cyto]/dt = k_trans − k_deg(O₂)·[Cyto] − k_imp·[Cyto] + k_exp·[Nuc]
    d[Nuc]/dt  = k_imp·[Cyto] − k_exp·[Nuc] − k_nuc_clear·[Nuc]

with hypoxia-scaled rates::

    k_imp = k_imp0 · (1 − O₂)
    k_exp = k_exp0 · O₂
    k_deg = k_deg0 · O₂

``k_nuc_clear`` keeps the nuclear pool finite under deep hypoxia (pure
task ODEs otherwise accumulate unbounded nuclear mass when k_exp→0).
Integrated with SciPy LSODA; pools are clamped to ``[0, pool_cap]``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
from scipy.integrate import solve_ivp


@dataclass(frozen=True)
class TranslocationParams:
    """HIF1A cytoplasmic / nuclear shuttling rate constants (1/min)."""

    k_trans: float = 0.06
    k_deg0: float = 0.22
    k_imp0: float = 0.35
    k_exp0: float = 0.10
    # Nuclear turnover so hypoxia does not accumulate unbounded nuclear mass
    k_nuc_clear: float = 0.08
    cyto0: float = 0.45
    nuc0: float = 0.05
    pool_cap: float = 1.0


def _interp_series(times: np.ndarray, values: np.ndarray, t: float) -> float:
    if times.size == 0:
        return 0.0
    if times.size == 1:
        return float(values[0])
    return float(np.interp(t, times, values, left=float(values[0]), right=float(values[-1])))


def integrate_hif1a_translocation(
    times: Sequence[float],
    o2: Sequence[float],
    *,
    synthesis: Optional[Sequence[float]] = None,
    params: Optional[TranslocationParams] = None,
    method: str = "LSODA",
) -> Dict[str, List[float]]:
    """
    Integrate 2-compartment HIF1A pools on the scrubber time grid.

    Parameters
    ----------
    times :
        Simulation time ticks (minutes), length N.
    o2 :
        Oxygen / hypoxia driver aligned to ``times`` (0–1).
    synthesis :
        Optional scale on ``k_trans`` (e.g. graph HIF1A activity), length N.
    """
    p = params or TranslocationParams()
    t = np.asarray(list(times), dtype=float).ravel()
    if t.size < 2:
        cyto = [max(0.0, float(p.cyto0))]
        nuc = [max(0.0, float(p.nuc0))]
        return {"cyto": cyto, "nuc": nuc}

    o2_arr = np.asarray(list(o2), dtype=float).ravel()
    if o2_arr.size != t.size:
        o2_arr = np.interp(
            t,
            np.linspace(float(t[0]), float(t[-1]), max(2, o2_arr.size)),
            o2_arr if o2_arr.size else np.array([0.35, 0.35]),
        )
    o2_arr = np.clip(o2_arr, 0.0, 1.0)

    if synthesis is not None:
        syn = np.asarray(list(synthesis), dtype=float).ravel()
        if syn.size != t.size:
            syn = np.interp(
                t,
                np.linspace(float(t[0]), float(t[-1]), max(2, syn.size)),
                syn if syn.size else np.array([1.0, 1.0]),
            )
        syn = np.clip(syn, 0.0, 2.0)
    else:
        syn = np.ones_like(t)

    y0 = np.array([max(0.0, float(p.cyto0)), max(0.0, float(p.nuc0))], dtype=float)
    cap = float(p.pool_cap)

    def rhs(_tt: float, y: np.ndarray) -> np.ndarray:
        cyto, nuc = float(max(0.0, y[0])), float(max(0.0, y[1]))
        o2_t = _interp_series(t, o2_arr, float(_tt))
        syn_t = _interp_series(t, syn, float(_tt))
        k_imp = float(p.k_imp0) * (1.0 - o2_t)
        k_exp = float(p.k_exp0) * o2_t
        k_deg = float(p.k_deg0) * o2_t
        k_trans = float(p.k_trans) * syn_t
        # Task mass-action + nuclear clearance for finite hypoxia steady state
        d_cyto = k_trans - k_deg * cyto - k_imp * cyto + k_exp * nuc
        d_nuc = k_imp * cyto - k_exp * nuc - float(p.k_nuc_clear) * nuc
        return np.array([d_cyto, d_nuc], dtype=float)

    sol = solve_ivp(
        rhs,
        (float(t[0]), float(t[-1])),
        y0,
        method=method,
        t_eval=t,
        rtol=1e-5,
        atol=1e-7,
        dense_output=False,
    )
    ys = np.clip(sol.y, 0.0, cap)
    cyto_out = [float(ys[0, i]) for i in range(ys.shape[1])]
    nuc_out = [float(ys[1, i]) for i in range(ys.shape[1])]
    while len(cyto_out) < t.size:
        cyto_out.append(cyto_out[-1] if cyto_out else float(p.cyto0))
        nuc_out.append(nuc_out[-1] if nuc_out else float(p.nuc0))
    return {"cyto": cyto_out[: t.size], "nuc": nuc_out[: t.size]}


def compartments_from_node_trajectories(
    time_steps: Sequence[float],
    nodes: Mapping[str, Sequence[float]],
    *,
    params: Optional[TranslocationParams] = None,
) -> Tuple[Dict[str, List[float]], Dict[str, Any]]:
    """
    Build ``{cyto, nuc}`` from graph node series (O2 + optional HIF1A).

    Returns compartments dict and a small metadata block for scrubber.metadata.
    """
    n = len(time_steps)
    if n == 0:
        return {"cyto": [], "nuc": []}, {"ok": False, "detail": "empty time_steps"}

    o2_series = list(nodes.get("O2") or [])
    if len(o2_series) != n:
        # Hypoxia default when O2 is not on the graph
        o2_series = [0.25] * n

    synthesis = None
    for sym in ("HIF1A", "EPAS1"):
        series = nodes.get(sym)
        if series and len(series) == n:
            # Normalize around 0.5 so synthesis stays O(1)
            synthesis = [0.5 + float(v) for v in series]
            break

    comps = integrate_hif1a_translocation(
        time_steps,
        o2_series,
        synthesis=synthesis,
        params=params,
        method="LSODA",
    )
    meta = {
        "ok": True,
        "method": "LSODA",
        "model": "hif1a_2compartment",
        "driver_o2_mean": float(np.mean(o2_series)) if o2_series else None,
        "has_hif_synthesis": synthesis is not None,
        "terminal": {
            "cyto": comps["cyto"][-1] if comps["cyto"] else 0.0,
            "nuc": comps["nuc"][-1] if comps["nuc"] else 0.0,
        },
    }
    return comps, meta


__all__ = [
    "TranslocationParams",
    "compartments_from_node_trajectories",
    "integrate_hif1a_translocation",
]
