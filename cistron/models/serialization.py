"""Frontend serialization schemas (scrubber / WebGL keyframes)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ScrubberPayload(BaseModel):
    """
    Single-source-of-truth trajectory payload for Studio scrubbing.

    ``time_steps`` is ``[0.0, 1.0, …, 60.0]`` minutes; ``nodes`` / ``trajectories``
    hold aligned samples of length ``len(time_steps)``. ``compartments`` carries
    server-side HIF1A cytoplasm / nucleus pools (no client Euler).
    """

    model_config = ConfigDict(extra="forbid")

    simulation_id: str = Field(default_factory=lambda: f"sim_{uuid.uuid4().hex[:12]}")
    time_steps: List[float]
    nodes: Dict[str, List[float]]
    trajectories: Dict[str, List[float]] = Field(
        default_factory=dict,
        description="Alias of node concentration series (single source of truth)",
    )
    edges: Dict[str, List[float]] = Field(
        default_factory=dict,
        description='Flux trajectories keyed as ``"SOURCE->TARGET"``',
    )
    compartments: Dict[str, List[float]] = Field(
        default_factory=dict,
        description="Server 2-compartment pools: ``cyto`` and ``nuc``",
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("time_steps")
    @classmethod
    def _nonempty_times(cls, v: List[float]) -> List[float]:
        if not v:
            raise ValueError("time_steps must be non-empty")
        return v

    def model_post_init(self, __context: Any) -> None:
        # Keep nodes ↔ trajectories synchronized for API consumers.
        if self.nodes and not self.trajectories:
            object.__setattr__(self, "trajectories", dict(self.nodes))
        elif self.trajectories and not self.nodes:
            object.__setattr__(self, "nodes", dict(self.trajectories))

    def n_keyframes(self) -> int:
        return len(self.time_steps)

    def edge_key(self, source: str, target: str) -> str:
        return f"{source}->{target}"

    def to_json_dict(self) -> Dict[str, Any]:
        """JSON-ready dict (aliases ``model_dump`` for frontend exporters)."""
        return self.model_dump(mode="json")
