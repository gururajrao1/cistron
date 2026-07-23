"""Frontend serialization schemas (scrubber / WebGL keyframes)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ScrubberPayload(BaseModel):
    """
    Optimized 61-keyframe trajectory for client-side linear interpolation.

    ``time_steps`` is ``[0.0, 1.0, …, 60.0]`` minutes; ``nodes`` / ``edges``
    hold aligned samples of length ``len(time_steps)``.
    """

    model_config = ConfigDict(extra="forbid")

    simulation_id: str = Field(default_factory=lambda: f"sim_{uuid.uuid4().hex[:12]}")
    time_steps: List[float]
    nodes: Dict[str, List[float]]
    edges: Dict[str, List[float]] = Field(
        default_factory=dict,
        description='Flux trajectories keyed as ``"SOURCE->TARGET"``',
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("time_steps")
    @classmethod
    def _nonempty_times(cls, v: List[float]) -> List[float]:
        if not v:
            raise ValueError("time_steps must be non-empty")
        return v

    def n_keyframes(self) -> int:
        return len(self.time_steps)

    def edge_key(self, source: str, target: str) -> str:
        return f"{source}->{target}"

    def to_json_dict(self) -> Dict[str, Any]:
        """JSON-ready dict (aliases ``model_dump`` for frontend exporters)."""
        return self.model_dump(mode="json")
