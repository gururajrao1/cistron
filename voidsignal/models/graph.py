"""
Pydantic graph schemas for OmniPath / SIGNOR activity-flow causal networks.

These models are the contract between data ingestion (``voidsignal.data``)
and ODE-ready :class:`~voidsignal.topology.SignalingNetwork` materialisation.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EdgeSign(int, Enum):
    """Strict causal polarity for activity-flow edges."""

    STIMULATION = 1
    INHIBITION = -1


class MechanismKind(str, Enum):
    """Latency class used to assign target time-constants τ."""

    ENZYMATIC = "enzymatic"
    """Post-translational (phosphorylation, ubiquitination, …) → τ ≈ 1 min."""

    TRANSCRIPTIONAL = "transcriptional"
    """Gene-regulatory / TF–target → τ ≈ 120 min."""


# Default latency tags (minutes)
TAU_ENZYMATIC_MIN = 1.0
TAU_TRANSCRIPTIONAL_MIN = 120.0

# Structural disruption threshold (kcal/mol)
DDG_DESTABILIZATION_KCAL = 2.5
DDG_ACTIVITY_SLOPE = 0.15


class ActivityFlowEdge(BaseModel):
    """One directed, signed OmniPath / SIGNOR activity-flow interaction."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(..., min_length=1, description="Upstream gene symbol")
    target: str = Field(..., min_length=1, description="Downstream gene symbol")
    sign: Literal[1, -1] = Field(..., description="+1 stimulation / −1 inhibition")
    is_stimulation: bool
    is_inhibition: bool
    consensus_modification: Optional[str] = None
    mechanism: MechanismKind = MechanismKind.ENZYMATIC
    sources: List[str] = Field(default_factory=list)
    datasets: List[str] = Field(default_factory=list)
    evidence_score: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("source", "target")
    @classmethod
    def _upper_symbol(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("gene symbol must be non-empty")
        return s

    @model_validator(mode="after")
    def _sign_consistency(self) -> "ActivityFlowEdge":
        if self.sign == 1 and not self.is_stimulation:
            raise ValueError("sign=+1 requires is_stimulation=True")
        if self.sign == -1 and not self.is_inhibition:
            raise ValueError("sign=-1 requires is_inhibition=True")
        if self.is_stimulation and self.is_inhibition:
            raise ValueError("edge cannot be both stimulation and inhibition")
        return self


class AmbiguousEdge(BaseModel):
    """Directed edge lacking a unique +1/−1 sign — flagged for manual review."""

    model_config = ConfigDict(extra="forbid")

    source: str
    target: str
    reason: str
    is_directed: bool = True
    is_stimulation: bool = False
    is_inhibition: bool = False
    consensus_modification: Optional[str] = None
    raw: Dict[str, Any] = Field(default_factory=dict)


class StructuralDisruption(BaseModel):
    """AlphaFold / VCF-derived missense structural impact for one node."""

    model_config = ConfigDict(extra="forbid")

    gene_symbol: str
    variant_hgvs: Optional[str] = None
    delta_delta_g: Optional[float] = Field(
        default=None,
        description="ΔΔG in kcal/mol (positive ⇒ destabilising)",
    )
    ramachandran_outlier: bool = False
    activity_weight: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Functional capacity multiplier w_i",
    )
    source: str = "alphafold_vcf"

    @field_validator("gene_symbol")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip()


class GraphNode(BaseModel):
    """Causal-graph node with latency τ and optional structural weight w_i."""

    model_config = ConfigDict(extra="forbid")

    gene_symbol: str = Field(..., min_length=1)
    tau_min: float = Field(
        default=TAU_ENZYMATIC_MIN,
        gt=0.0,
        description="Node time-constant τ_i in minutes",
    )
    activity_weight: float = Field(default=1.0, ge=0.0, le=1.0)
    structural: Optional[StructuralDisruption] = None
    initial_concentration: float = Field(default=0.4, ge=0.0)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("gene_symbol")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip()


class CausalActivityGraph(BaseModel):
    """
    Clean directed activity-flow graph ready for ODE materialisation.

    Only edges with unambiguous signs (+1 or −1) appear in ``edges``.
    Ambiguous candidates are retained in ``ambiguous`` for curation.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = "activity_flow"
    organism_id: int = 9606
    nodes: Dict[str, GraphNode] = Field(default_factory=dict)
    edges: List[ActivityFlowEdge] = Field(default_factory=list)
    ambiguous: List[AmbiguousEdge] = Field(default_factory=list)
    provenance: Dict[str, Any] = Field(default_factory=dict)

    def node_symbols(self) -> List[str]:
        return sorted(self.nodes.keys())

    def edge_count(self) -> int:
        return len(self.edges)

    def summary(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "n_nodes": len(self.nodes),
            "n_edges": len(self.edges),
            "n_ambiguous": len(self.ambiguous),
            "n_enzymatic": sum(1 for e in self.edges if e.mechanism == MechanismKind.ENZYMATIC),
            "n_transcriptional": sum(
                1 for e in self.edges if e.mechanism == MechanismKind.TRANSCRIPTIONAL
            ),
        }
