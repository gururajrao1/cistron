"""Causal BioReasoner context payloads (Domain 12)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class CausalPathContext(BaseModel):
    """One extracted high-throughput causal cascade."""

    model_config = ConfigDict(extra="forbid")

    nodes: List[str]
    state_deltas: Dict[str, float]
    cumulative_attention: float = Field(
        ...,
        description="Product of α along path edges (throughput proxy)",
    )
    mechanisms: List[str] = Field(
        default_factory=list,
        description="Per-hop mechanism tags aligned to consecutive node pairs",
    )
    path_distance: float = Field(
        default=0.0,
        description="Sum of −log(α+ε) edge distances (Dijkstra cost)",
    )
    edge_attentions: List[float] = Field(
        default_factory=list,
        description="α on each hop (length = len(nodes) − 1)",
    )
    latencies_min: Dict[str, float] = Field(
        default_factory=dict,
        description="τ_i (minutes) for path nodes from the causal graph",
    )
    signs: List[int] = Field(
        default_factory=list,
        description="Edge signs (+1/−1) along the path",
    )


class CausalContextPayload(BaseModel):
    """Deterministic grounding payload for hallucination-free NLP briefs."""

    model_config = ConfigDict(extra="forbid")

    simulation_id: str
    extracted_paths: List[CausalPathContext]
    top_master_regulator: str
    perturbed_nodes: List[str]
    source_node: Optional[str] = None
    target_node: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_json_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")
