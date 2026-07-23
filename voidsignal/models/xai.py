"""XAI attribution models for the Virtual Cellular Laboratory."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class FeatureAttribution(BaseModel):
    """Per-feature contribution to pathway output change."""

    model_config = ConfigDict(extra="forbid")

    feature_name: str
    value: float
    attribution: float


class NodeShapAttribution(BaseModel):
    """Node-level SHAP / IG-proxy importance for one protein."""

    model_config = ConfigDict(extra="forbid")

    node: str
    importance: float
    rank: int = 0
    feature_attributions: List[FeatureAttribution] = Field(default_factory=list)
    delta_y: float = 0.0
    capacity: float = 1.0
    is_knocked_out: bool = False


class EdgeFlowImpact(BaseModel):
    """Attentive flow decomposition of GAT αᵢⱼ into edge impact."""

    model_config = ConfigDict(extra="forbid")

    edge_key: str
    source: str
    target: str
    alpha: float
    impact_score: float
    mean_flux: float = 0.0


class CounterfactualResult(BaseModel):
    """What-if restoration / knockout hypothesis with quantified effect."""

    model_config = ConfigDict(extra="forbid")

    hypothesis: str
    node: str
    intervention: str
    readout_node: str
    baseline_readout: float
    counterfactual_readout: float
    fold_change: float
    delta_absolute: float
    horizon_min: float = 15.0
    narrative: str = ""


class XAIAttributionResult(BaseModel):
    """Unified XAI payload for SHAP, counterfactuals, and attentive flow."""

    model_config = ConfigDict(extra="forbid")

    node_attributions: List[NodeShapAttribution] = Field(default_factory=list)
    edge_flow_impacts: List[EdgeFlowImpact] = Field(default_factory=list)
    counterfactuals: List[CounterfactualResult] = Field(default_factory=list)
    output_nodes: List[str] = Field(default_factory=list)
    output_delta_sum: float = 0.0
    elapsed_ms: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ScientistReasoning(BaseModel):
    """Instant AI Scientist filter-reasoning brief."""

    model_config = ConfigDict(extra="forbid")

    brief: str
    sentiment: str = Field(
        default="neutral",
        description="up | down | mixed | neutral — drives UI pulse colour",
    )
    total_flux_delta: float = 0.0
    top_node_deltas: Dict[str, float] = Field(default_factory=dict)
    attention_reroutes: Dict[str, float] = Field(default_factory=dict)
    perturbation_summary: str = ""
    elapsed_ms: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class PreviousStateSummary(BaseModel):
    """Optional prior-run snapshot for delta scientist reasoning."""

    model_config = ConfigDict(extra="forbid")

    node_finals: Dict[str, float] = Field(default_factory=dict)
    attention_matrix: Dict[str, float] = Field(default_factory=dict)
    edge_mean_flux: Dict[str, float] = Field(default_factory=dict)
    knockouts: List[str] = Field(default_factory=list)
    clamps: Dict[str, float] = Field(default_factory=dict)
    condition_query: Optional[str] = None
    scientist_brief: Optional[str] = None


__all__ = [
    "CounterfactualResult",
    "EdgeFlowImpact",
    "FeatureAttribution",
    "NodeShapAttribution",
    "PreviousStateSummary",
    "ScientistReasoning",
    "XAIAttributionResult",
]
