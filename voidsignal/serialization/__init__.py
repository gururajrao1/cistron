"""Trajectory serialization for frontend scrubbers / WebGL lerp."""

from voidsignal.serialization.scrubber import (
    DEFAULT_KEYFRAME_END_MIN,
    DEFAULT_N_INTERVALS,
    SimulationResult,
    build_keyframe_grid,
    compute_edge_flux,
    edge_flux_key,
    sample_uniform_keyframes,
    scrub_simulation,
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
