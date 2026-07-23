"""Prioritization / attention result schemas for the AI target module."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator


class NodeFeatureVector(BaseModel):
    """5D time-aware node feature (also exposed as a NumPy vector via helpers)."""

    model_config = ConfigDict(extra="forbid")

    y_init: float
    y_final: float
    delta_y: float
    capacity: float
    is_knocked_out: bool

    def as_array(self) -> List[float]:
        """Return ``[y0, y60, Δy, w, is_ko]`` as plain floats."""
        return [
            float(self.y_init),
            float(self.y_final),
            float(self.delta_y),
            float(self.capacity),
            1.0 if self.is_knocked_out else 0.0,
        ]


class CombinationCandidate(BaseModel):
    """One dual-inhibition pair evaluated for synthetic lethality."""

    model_config = ConfigDict(extra="forbid")

    target_a: str
    target_b: str
    output_sum: float = Field(
        ...,
        description="Σ y_output(t_60) under dual knockout",
    )
    baseline_output_sum: float
    single_a_output_sum: float
    single_b_output_sum: float
    synergy_score: float = Field(
        ...,
        description="Positive ⇒ combo beats Bliss-independent expectation",
    )

    @property
    def pair(self) -> Tuple[str, str]:
        return (self.target_a, self.target_b)


class PrioritizationResult(BaseModel):
    """Graph-attention + master-regulator ranking for one scrubber trajectory."""

    model_config = ConfigDict(extra="forbid")

    node_vectors: Dict[str, NodeFeatureVector]
    attention_matrix: Dict[str, float] = Field(
        default_factory=dict,
        description='α_ij keyed as ``"SOURCE->TARGET"`` (edge j→i)',
    )
    master_regulators: List[Tuple[str, float]] = Field(
        default_factory=list,
        description="Nodes ranked by descending driver score S_i",
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("master_regulators")
    @classmethod
    def _pairs(cls, v: List[Tuple[str, float]]) -> List[Tuple[str, float]]:
        return [(str(name), float(score)) for name, score in v]
