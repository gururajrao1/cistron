"""Pydantic request / response models for the Cistron REST API."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cistron.models.prioritization import PrioritizationResult
from cistron.models.reasoner import CausalContextPayload
from cistron.models.serialization import ScrubberPayload
from cistron.models.xai import (
    PreviousStateSummary,
    ScientistReasoning,
    XAIAttributionResult,
)
from cistron.models.topology_analysis import TopologicalAnalysis
from cistron.models.omics import OmicsProfile


class DrugDoseRequest(BaseModel):
    """PK/PD inhibitor occupancy against one target node."""

    model_config = ConfigDict(extra="forbid")

    target: str = Field(..., min_length=1)
    c_drug: float = Field(default=0.0, ge=0.0, description="Drug concentration C")
    concentration: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Alias for c_drug",
    )
    ki: float = Field(..., gt=0.0, description="Inhibition constant Ki")

    @model_validator(mode="after")
    def _resolve_concentration(self) -> "DrugDoseRequest":
        if self.concentration is not None and self.c_drug == 0.0:
            object.__setattr__(self, "c_drug", float(self.concentration))
        elif self.concentration is not None:
            object.__setattr__(self, "c_drug", float(self.concentration))
        return self

class SimulateRequest(BaseModel):
    """Run Hill-cube ODE integration + 61-keyframe scrubber export."""

    model_config = ConfigDict(extra="forbid")

    preset: str = Field(default="hypoxia", description="Network preset id")
    t_end: float = Field(default=60.0, gt=0.0)
    knockouts: List[str] = Field(default_factory=list)
    clamps: Dict[str, float] = Field(default_factory=dict)
    drugs: List[DrugDoseRequest] = Field(default_factory=list)
    simulation_id: Optional[str] = None
    dense_output_points: int = Field(
        default=61,
        ge=2,
        le=501,
        description="Integrator eval grid size (61 keeps API latency low)",
    )


class PrioritizeRequest(BaseModel):
    """Graph-attention prioritization over an existing scrubber trajectory."""

    model_config = ConfigDict(extra="forbid")

    preset: str = Field(default="hypoxia")
    payload: ScrubberPayload


class ReasonRequest(BaseModel):
    """Causal BioReasoner path extraction + grounded narrative brief."""

    model_config = ConfigDict(extra="forbid")

    preset: str = Field(default="hypoxia")
    payload: ScrubberPayload
    source_node: str = Field(..., min_length=1)
    target_node: str = Field(..., min_length=1)
    k: int = Field(default=3, ge=1, le=20)
    include_prompt: bool = True
    include_brief: bool = True
    include_prioritization: bool = False


class ReasonResponse(BaseModel):
    """Structured context + optional prompt / deterministic brief."""

    model_config = ConfigDict(extra="forbid")

    context: CausalContextPayload
    brief: Optional[str] = None
    prompt: Optional[str] = None
    prioritization: Optional[PrioritizationResult] = None
    elapsed_ms: float = 0.0


class PresetSummary(BaseModel):
    """Lightweight preset catalogue entry for the UI."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    n_nodes: int
    n_edges: int
    description: str = ""
    nodes: List[str] = Field(default_factory=list)


class PresetDetail(BaseModel):
    """Full preset topology for canvas hydration."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    organism_id: int
    nodes: Dict[str, Dict[str, Any]]
    edges: List[Dict[str, Any]]
    provenance: Dict[str, Any] = Field(default_factory=dict)


class SearchAndSimulateRequest(BaseModel):
    """Free-text condition → resolve network → full lab pipeline."""

    model_config = ConfigDict(extra="forbid")

    condition_query: str = Field(..., min_length=1, description="Disease / stress / drug query")
    custom_knockouts: List[str] = Field(default_factory=list)
    custom_clamps: Dict[str, float] = Field(default_factory=dict)
    drugs: List[DrugDoseRequest] = Field(
        default_factory=list,
        description="Pharmacological inhibitors (alias: drug_perturbations)",
    )
    drug_perturbations: List[DrugDoseRequest] = Field(
        default_factory=list,
        description="Alias for drugs — inhibitors with concentration C and Ki",
    )
    previous_state_summary: Optional[PreviousStateSummary] = None
    t_end: float = Field(default=60.0, gt=0.0)
    dense_output_points: int = Field(default=61, ge=2, le=501)
    source_node: Optional[str] = None
    target_node: Optional[str] = None
    simulation_id: Optional[str] = None
    use_omnipath: bool = True
    selected_sources: List[str] = Field(
        default_factory=list,
        description=(
            "Knowledge sources to query: local, omnipath, signor, kegg, reactome, "
            "string, biogrid, uniprot. Empty = all sources."
        ),
    )
    include_synthetic_lethality: bool = Field(
        default=False,
        description=(
            "Run pairwise virtual-KO synthetic lethality (slow). "
            "Off by default so Studio stays interactive; enable from Combinations."
        ),
    )
    @model_validator(mode="after")
    def _merge_drug_aliases(self) -> "SearchAndSimulateRequest":
        if self.drug_perturbations:
            merged = list(self.drugs) + list(self.drug_perturbations)
            object.__setattr__(self, "drugs", merged)
            object.__setattr__(self, "drug_perturbations", [])
        return self


class SearchAndSimulateResponse(BaseModel):
    """Unified dynamic-condition laboratory response."""

    model_config = ConfigDict(extra="forbid")

    query: str
    profile_id: str
    resolved_graph: PresetDetail
    scrubber_payload: ScrubberPayload
    prioritization: PrioritizationResult
    causal_brief: ReasonResponse
    xai_attributions: Optional[XAIAttributionResult] = None
    scientist_reasoning: Optional[ScientistReasoning] = None
    state_summary: Optional[PreviousStateSummary] = None
    topological_analysis: Optional[TopologicalAnalysis] = None
    default_clamps: Dict[str, float] = Field(default_factory=dict)
    source_node: str
    target_node: str
    resolve_ms: float = 0.0
    elapsed_ms: float = 0.0
    stages: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class NodeInspectorResponse(BaseModel):
    """Biophysics card for a clicked canvas node."""

    model_config = ConfigDict(extra="forbid")

    gene_symbol: str
    uniprot_id: Optional[str] = None
    full_name: Optional[str] = None
    localization: Optional[str] = None
    function: Optional[str] = None
    y_init: float = 0.0
    y_final: float = 0.0
    delta_y: float = 0.0
    capacity: float = 1.0
    is_knocked_out: bool = False
    shap_importance: Optional[float] = None
    shap_rank: Optional[int] = None
    upstream: List[Dict[str, Any]] = Field(default_factory=list)
    downstream: List[Dict[str, Any]] = Field(default_factory=list)
    feature_attributions: List[Dict[str, Any]] = Field(default_factory=list)


class ConditionSuggestion(BaseModel):
    label: str
    query: str


class HealthResponse(BaseModel):
    """Connectivity probe — status, UTC timestamp, and loaded data handles."""

    status: str = "ok"
    service: str = "cistron-api"
    version: str = "0.22.0"
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="UTC ISO-8601 server timestamp",
    )
    database_handles: Dict[str, Any] = Field(
        default_factory=dict,
        description="Loaded presets, dynamic graphs, and condition libraries",
    )


class SimulateResponse(BaseModel):
    """Scrubber payload plus light request echo for the timeline UI."""

    model_config = ConfigDict(extra="forbid")

    payload: ScrubberPayload
    preset: str
    elapsed_ms: float = 0.0


class PrioritizeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result: PrioritizationResult
    preset: str
    elapsed_ms: float = 0.0


class OmicsSimulateRequest(BaseModel):
    """Run the lab pipeline from an uploaded / in-memory omics profile."""

    model_config = ConfigDict(extra="forbid")

    profile: OmicsProfile
    t_end: float = Field(default=60.0, gt=0.0)
    knockouts: List[str] = Field(default_factory=list)
    drugs: List[DrugDoseRequest] = Field(default_factory=list)
    dense_output_points: int = Field(default=61, ge=2, le=501)
    source_node: Optional[str] = None
    target_node: Optional[str] = None
    simulation_id: Optional[str] = None
    scaling_factor: float = Field(
        default=1.0,
        gt=0.0,
        description="Sigmoid steepness k for log2_fc → y₀ mapping",
    )
    baseline_y0: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Default y₀ for network nodes missing from the profile",
    )
    previous_state_summary: Optional[PreviousStateSummary] = None
