"""
Uniform keyframe trajectory scrubber for Hill-cube ODE outputs.

Downsamples dense ``HillCubeEngine`` / ``SimulationResult`` trajectories to
61 integer-minute frames (t = 0…60) and computes per-edge Hill-gate flux for
frontend WebGL / Canvas lerp playback.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Union
import uuid

import numpy as np

from cistron.engine.solver import (
    DEFAULT_EC50,
    DEFAULT_HILL_N,
    HillCubeEngine,
    HillCubeResult,
    hill_activation,
    hill_inhibition,
)
from cistron.models.graph import CausalActivityGraph
from cistron.models.serialization import ScrubberPayload

# Public alias requested by the serialization contract
SimulationResult = HillCubeResult

DEFAULT_KEYFRAME_END_MIN = 60.0
DEFAULT_N_INTERVALS = 60  # → 61 samples at t = 0,1,…,60


def edge_flux_key(source: str, target: str) -> str:
    return f"{source}->{target}"


def _interp_series(times: np.ndarray, values: np.ndarray, query_t: np.ndarray) -> np.ndarray:
    """
    Evaluate a 1-D trajectory at ``query_t`` via linear interpolation.

    Prefers ``scipy.interpolate.interp1d`` when available; falls back to
    ``numpy.interp``. Extrapolates by clamping to endpoint values.
    """
    t = np.asarray(times, dtype=float).ravel()
    y = np.asarray(values, dtype=float).ravel()
    if t.size == 0:
        return np.zeros_like(query_t, dtype=float)
    if t.size == 1:
        return np.full_like(query_t, float(y[0]), dtype=float)

    # Ensure strictly increasing time for interpolators
    order = np.argsort(t)
    t = t[order]
    y = y[order]
    # Drop duplicate times (keep last)
    _, uniq_idx = np.unique(t, return_index=True)
    # unique returns first index; rebuild keeping last occurrence
    mask = np.ones(t.size, dtype=bool)
    for i in range(t.size - 1):
        if t[i] == t[i + 1]:
            mask[i] = False
    t = t[mask]
    y = y[mask]

    q = np.asarray(query_t, dtype=float)
    try:
        from scipy.interpolate import interp1d

        fn = interp1d(
            t,
            y,
            kind="linear",
            bounds_error=False,
            fill_value=(float(y[0]), float(y[-1])),
            assume_sorted=True,
        )
        return np.asarray(fn(q), dtype=float)
    except Exception:
        return np.interp(q, t, y, left=float(y[0]), right=float(y[-1]))


def compute_edge_flux(
    y_source: float,
    *,
    sign: int,
    hill_n: float = DEFAULT_HILL_N,
    ec50: float = DEFAULT_EC50,
) -> float:
    """
    Instantaneous Hill-gate flux on edge j→i.

    * Stimulation (+1): ``y^n / (y^n + EC50^n)``
    * Inhibition (−1): ``1 − y^n / (y^n + EC50^n)``
    """
    if sign >= 0:
        return float(hill_activation(y_source, n=hill_n, ec50=ec50))
    return float(hill_inhibition(y_source, n=hill_n, ec50=ec50))


def build_keyframe_grid(
    *,
    t_end: float = DEFAULT_KEYFRAME_END_MIN,
    n_intervals: int = DEFAULT_N_INTERVALS,
) -> np.ndarray:
    """Return ``[0, 1, …, t_end]`` with ``n_intervals + 1`` samples."""
    if n_intervals < 1:
        raise ValueError("n_intervals must be ≥ 1")
    if t_end <= 0.0:
        raise ValueError("t_end must be positive")
    return np.linspace(0.0, float(t_end), int(n_intervals) + 1)


def sample_uniform_keyframes(
    result: Union[HillCubeResult, SimulationResult],
    graph: CausalActivityGraph,
    *,
    t_end: float = DEFAULT_KEYFRAME_END_MIN,
    n_intervals: int = DEFAULT_N_INTERVALS,
    hill_n: float = DEFAULT_HILL_N,
    ec50: float = DEFAULT_EC50,
    simulation_id: Optional[str] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> ScrubberPayload:
    """
    Downsample an ODE trajectory to uniform integer-minute keyframes + edge fluxes.

    Parameters
    ----------
    result :
        Output of :meth:`HillCubeEngine.simulate` (aliased as ``SimulationResult``).
    graph :
        Source :class:`CausalActivityGraph` (provides signed edges).
    """
    grid = build_keyframe_grid(t_end=t_end, n_intervals=n_intervals)
    times = np.asarray(result.times, dtype=float)

    nodes: Dict[str, List[float]] = {}
    for sym in sorted(set(result.symbols) | set(graph.nodes.keys())):
        if sym in result.states:
            series = np.asarray(result.states[sym], dtype=float)
        elif sym in result.y0:
            series = np.full_like(times, float(result.y0[sym]), dtype=float)
        else:
            series = np.zeros_like(times, dtype=float)
        sampled = _interp_series(times, series, grid)
        nodes[sym] = [float(min(1.0, max(0.0, v))) for v in sampled]

    edges: Dict[str, List[float]] = {}
    for edge in graph.edges:
        key = edge_flux_key(edge.source, edge.target)
        src_traj = nodes.get(edge.source)
        if src_traj is None:
            # Source missing from state — zero flux
            edges[key] = [0.0] * len(grid)
            continue
        flux = [
            compute_edge_flux(y, sign=int(edge.sign), hill_n=hill_n, ec50=ec50)
            for y in src_traj
        ]
        edges[key] = flux

    meta: Dict[str, Any] = {
        "t_end_min": float(t_end),
        "n_keyframes": int(len(grid)),
        "n_intervals": int(n_intervals),
        "hill_n": float(hill_n),
        "ec50": float(ec50),
        "graph_name": graph.name,
        "engine_success": bool(getattr(result, "success", True)),
        "engine_message": str(getattr(result, "message", "")),
        "weights": dict(getattr(result, "weights", {}) or {}),
        "y0": dict(getattr(result, "y0", {}) or {}),
    }
    if getattr(result, "metadata", None):
        meta["engine"] = dict(result.metadata)
    if metadata:
        meta.update(dict(metadata))

    return ScrubberPayload(
        simulation_id=simulation_id or f"sim_{uuid.uuid4().hex[:12]}",
        time_steps=[float(t) for t in grid],
        nodes=nodes,
        edges=edges,
        metadata=meta,
    )


def scrub_simulation(
    engine: HillCubeEngine,
    *,
    t_end: float = DEFAULT_KEYFRAME_END_MIN,
    n_intervals: int = DEFAULT_N_INTERVALS,
    simulate_kwargs: Optional[Mapping[str, Any]] = None,
    simulation_id: Optional[str] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> ScrubberPayload:
    """
    Run :meth:`HillCubeEngine.simulate` (ensuring coverage to ``t_end``) and
    serialize a scrubber payload.
    """
    kw = dict(simulate_kwargs or {})
    # Ensure integrator spans at least the keyframe horizon
    sim_t_end = max(float(t_end), float(kw.pop("t_end", t_end)))
    result = engine.simulate(t_end=sim_t_end, **kw)
    return sample_uniform_keyframes(
        result,
        engine.graph,
        t_end=t_end,
        n_intervals=n_intervals,
        simulation_id=simulation_id,
        metadata=metadata,
    )


__all__ = [
    "DEFAULT_KEYFRAME_END_MIN",
    "DEFAULT_N_INTERVALS",
    "SimulationResult",
    "build_keyframe_grid",
    "compute_edge_flux",
    "edge_flux_key",
    "sample_uniform_keyframes",
    "scrub_simulation",
]
