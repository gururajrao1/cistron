"""Numpy-only Saltelli-lite first-order sensitivity (no SALib dependency).

Samples node capacity / τ multipliers and attributes variance of a readout
to each factor — Free-safe and honest about being a lightweight estimator.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence
import time

import numpy as np

from cistron.engine.solver import DrugDose, HillCubeConfig, HillCubeEngine
from cistron.models.graph import CausalActivityGraph


def _terminal(eng_payload_nodes: Dict[str, List[float]], symbol: str) -> float:
    series = eng_payload_nodes.get(symbol) or []
    return float(series[-1]) if series else 0.0


def saltelli_lite(
    graph: CausalActivityGraph,
    *,
    readout: str,
    n_base: int = 8,
    clamps: Optional[Dict[str, float]] = None,
    knockouts: Optional[Sequence[str]] = None,
    t_end: float = 60.0,
    seed: int = 7,
) -> Dict[str, Any]:
    """
    One-at-a-time + Saltelli-style A/B matrices for first-order S_i proxies.

    Factors = activity_weight and tau_min for up to 10 non-knocked nodes.
    """
    t0 = time.perf_counter()
    rng = np.random.default_rng(seed)
    nodes = [s for s in graph.nodes.keys() if s not in set(knockouts or [])]
    nodes = nodes[:10]
    if len(nodes) < 2 or readout not in graph.nodes:
        return {
            "readout": readout,
            "factors": [],
            "S_i": [],
            "S_Ti": [],
            "n_base": n_base,
            "elapsed_ms": 0.0,
            "method": "saltelli_lite",
            "ok": False,
            "detail": "Need ≥2 free nodes and a valid readout",
        }

    def eval_factors(factors: np.ndarray) -> float:
        # factors layout: [w0, tau0, w1, tau1, ...]
        g = graph.model_copy(deep=True)
        for i, sym in enumerate(nodes):
            n = g.nodes[sym]
            w = float(np.clip(factors[2 * i], 0.05, 1.0))
            tau = float(np.clip(factors[2 * i + 1], 0.25, 4.0))
            g.nodes[sym] = n.model_copy(
                update={
                    "activity_weight": w,
                    "tau_min": max(0.05, tau * float(n.tau_min or 1.0)),
                }
            )
        eng = HillCubeEngine(
            g,
            config=HillCubeConfig(t_end=float(t_end), dense_output_points=21, method="LSODA"),
        )
        for sym, val in (clamps or {}).items():
            if sym in eng.symbols:
                eng.clamp(sym, float(val))
        if knockouts:
            known = [k for k in knockouts if k in eng.symbols]
            if known:
                eng.knockout(list(known))
        res = eng.simulate()
        traj = {s: [float(x) for x in res.states.get(s, [])] for s in eng.symbols}
        return _terminal(traj, readout)

    d = len(nodes) * 2
    n = max(4, int(n_base))
    A = rng.uniform(0.2, 1.2, size=(n, d))
    B = rng.uniform(0.2, 1.2, size=(n, d))
    yA = np.array([eval_factors(A[i]) for i in range(n)], dtype=float)
    yB = np.array([eval_factors(B[i]) for i in range(n)], dtype=float)
    var_y = float(np.var(np.concatenate([yA, yB])) + 1e-12)

    S_i: List[float] = []
    S_Ti: List[float] = []
    labels: List[str] = []
    for j, sym in enumerate(nodes):
        for kind, offset in (("weight", 0), ("tau", 1)):
            col = 2 * j + offset
            Ab = A.copy()
            Ab[:, col] = B[:, col]
            yAb = np.array([eval_factors(Ab[i]) for i in range(n)], dtype=float)
            # First-order (Saltelli): S_i ≈ mean(yB * (yAb - yA)) / var
            si = float(np.mean(yB * (yAb - yA)) / var_y)
            # Total-effect proxy: S_Ti ≈ 0.5 * mean((yA - yAb)^2) / var
            sti = float(0.5 * np.mean((yA - yAb) ** 2) / var_y)
            S_i.append(max(0.0, min(1.5, si)))
            S_Ti.append(max(0.0, min(2.0, sti)))
            labels.append(f"{sym}:{kind}")

    # Rank by total effect
    order = sorted(range(len(labels)), key=lambda i: -S_Ti[i])
    return {
        "readout": readout,
        "factors": [labels[i] for i in order],
        "S_i": [S_i[i] for i in order],
        "S_Ti": [S_Ti[i] for i in order],
        "n_base": n,
        "n_factors": len(labels),
        "elapsed_ms": (time.perf_counter() - t0) * 1000.0,
        "method": "saltelli_lite_numpy",
        "ok": True,
        "detail": "Lightweight Saltelli-style indices (not full SALib QMC).",
    }
