"""Topological vulnerability & synthetic lethality result models."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class BottleneckNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node: str
    betweenness: float = 0.0
    hub_degree: float = 0.0
    pagerank: float = 0.0
    role: str = "Signaling Bottleneck"


class FeedbackLoop(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle: List[str]
    type: str = Field(description="Negative Feedback | Positive Feedback | Mixed Feedback")
    length: int = 0
    sign_product: int = 1


class SyntheticLethalPair(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pair: List[str]
    synergy_score: float = 0.0
    dual_output_sum: float = 0.0
    single_a_output: float = 0.0
    single_b_output: float = 0.0
    baseline_output: float = 0.0
    explanation: str = ""


class TopologicalAnalysis(BaseModel):
    """Automated topological vulnerability payload for the lab API."""

    model_config = ConfigDict(extra="forbid")

    bottlenecks: List[BottleneckNode] = Field(default_factory=list)
    feedback_loops: List[FeedbackLoop] = Field(default_factory=list)
    synthetic_lethal_pairs: List[SyntheticLethalPair] = Field(default_factory=list)
    elapsed_ms: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "BottleneckNode",
    "FeedbackLoop",
    "SyntheticLethalPair",
    "TopologicalAnalysis",
]
