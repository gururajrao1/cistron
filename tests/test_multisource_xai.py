"""
API schema contracts for multi-source resolve + XAI + AI Scientist.

Defines and validates Pydantic contracts used by upcoming Cistron backend
updates, and asserts that ``POST /api/v1/search-and-simulate`` request /
response shapes remain stable.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from cistron.api.schemas import (
    DrugDoseRequest,
    NodeInspectorResponse,
    PresetDetail,
    ReasonResponse,
    SearchAndSimulateRequest,
    SearchAndSimulateResponse,
)
from cistron.models.prioritization import NodeFeatureVector, PrioritizationResult
from cistron.models.reasoner import CausalContextPayload, CausalPathContext
from cistron.models.serialization import ScrubberPayload
from cistron.models.topology_analysis import TopologicalAnalysis
from cistron.models.xai import (
    CounterfactualResult,
    EdgeFlowImpact,
    FeatureAttribution,
    NodeShapAttribution,
    ScientistReasoning,
    XAIAttributionResult,
)

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from cistron.api.app import create_app

# ---------------------------------------------------------------------------
# Schema contracts (canonical shapes the lab API must honour)
# ---------------------------------------------------------------------------

KNOWN_SOURCES = (
    "local",
    "omnipath",
    "signor",
    "kegg",
    "reactome",
    "string",
    "biogrid",
    "uniprot",
)


class MultiSourceProvenance(BaseModel):
    """Provenance badge payload from the multi-source knowledge resolver."""

    model_config = ConfigDict(extra="allow")

    query: str
    profile_id: str
    selected_sources: List[str] = Field(default_factory=list)
    source_status: Dict[str, str] = Field(default_factory=dict)
    n_edges_fused: int = 0
    n_nodes: int = 0
    builder: str = "resolve_multisource_network"


class NodeBiophysics(BaseModel):
    """5D node feature vector + optional inspector / SHAP overlays."""

    model_config = ConfigDict(extra="forbid")

    gene_symbol: str
    y_init: float
    y_final: float
    delta_y: float
    capacity: float = 1.0
    is_knocked_out: bool = False
    uniprot_id: Optional[str] = None
    full_name: Optional[str] = None
    localization: Optional[str] = None
    function: Optional[str] = None
    shap_importance: Optional[float] = None
    shap_rank: Optional[int] = None
    feature_attributions: List[Dict[str, Any]] = Field(default_factory=list)

    def as_5d(self) -> List[float]:
        return [
            float(self.y_init),
            float(self.y_final),
            float(self.delta_y),
            float(self.capacity),
            1.0 if self.is_knocked_out else 0.0,
        ]


class XAIAttributions(BaseModel):
    """SHAP / IG-proxy node importances, edge flow, and counterfactuals."""

    model_config = ConfigDict(extra="forbid")

    node_attributions: List[NodeShapAttribution] = Field(default_factory=list)
    edge_flow_impacts: List[EdgeFlowImpact] = Field(default_factory=list)
    counterfactuals: List[CounterfactualResult] = Field(default_factory=list)
    output_nodes: List[str] = Field(default_factory=list)
    output_delta_sum: float = 0.0
    elapsed_ms: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AIScientistReasoning(BaseModel):
    """Instant mechanistic brief — generation must stay under 20 ms."""

    model_config = ConfigDict(extra="forbid")

    brief: str
    sentiment: str = "neutral"
    total_flux_delta: float = 0.0
    top_node_deltas: Dict[str, float] = Field(default_factory=dict)
    attention_reroutes: Dict[str, float] = Field(default_factory=dict)
    perturbation_summary: str = ""
    elapsed_ms: float = Field(..., description="Must be < 20 ms")
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Mock factory — full search-and-simulate success body
# ---------------------------------------------------------------------------


def _mock_scrubber(n_frames: int = 61) -> ScrubberPayload:
    t = [float(i) for i in range(n_frames)]
    nodes = {
        "EGFR": [0.2 + 0.01 * i for i in range(n_frames)],
        "BRAF": [0.3 + 0.008 * i for i in range(n_frames)],
        "MAPK1": [0.1 + 0.012 * i for i in range(n_frames)],
        "VEGFA": [0.05 + 0.015 * i for i in range(n_frames)],
    }
    edges = {
        "EGFR->BRAF": [0.4] * n_frames,
        "BRAF->MAPK1": [0.5] * n_frames,
        "MAPK1->VEGFA": [0.35] * n_frames,
    }
    return ScrubberPayload(
        simulation_id="mock_sim_contract",
        time_steps=t,
        nodes=nodes,
        edges=edges,
        metadata={"n_keyframes": n_frames, "source": "mock"},
    )


def _mock_provenance() -> MultiSourceProvenance:
    return MultiSourceProvenance(
        query="Glioblastoma EGFR resistance",
        profile_id="glioblastoma",
        selected_sources=[
            "local",
            "omnipath",
            "reactome",
            "string",
            "kegg",
            "uniprot",
        ],
        source_status={
            "local": "ok",
            "omnipath": "ok",
            "reactome": "ok",
            "string": "ok",
            "kegg": "ok",
            "uniprot": "ok",
            "signor": "skipped",
            "biogrid": "skipped",
        },
        n_edges_fused=24,
        n_nodes=12,
        builder="resolve_multisource_network",
    )


def _mock_xai() -> XAIAttributions:
    return XAIAttributions(
        node_attributions=[
            NodeShapAttribution(
                node="EGFR",
                importance=0.82,
                rank=1,
                feature_attributions=[
                    FeatureAttribution(feature_name="y_init", value=0.2, attribution=0.05),
                    FeatureAttribution(feature_name="y_final", value=0.8, attribution=0.21),
                    FeatureAttribution(feature_name="delta_y", value=0.6, attribution=0.40),
                    FeatureAttribution(feature_name="capacity", value=1.0, attribution=0.10),
                    FeatureAttribution(
                        feature_name="is_knocked_out", value=0.0, attribution=0.06
                    ),
                ],
                delta_y=0.6,
                capacity=1.0,
            ),
            NodeShapAttribution(
                node="BRAF",
                importance=0.55,
                rank=2,
                feature_attributions=[
                    FeatureAttribution(feature_name="delta_y", value=0.4, attribution=0.30),
                ],
                delta_y=0.4,
            ),
        ],
        edge_flow_impacts=[
            EdgeFlowImpact(
                edge_key="EGFR->BRAF",
                source="EGFR",
                target="BRAF",
                alpha=0.71,
                impact_score=0.64,
                mean_flux=0.4,
            )
        ],
        counterfactuals=[
            CounterfactualResult(
                hypothesis="Restore EGFR capacity",
                node="EGFR",
                intervention="capacity_restore",
                readout_node="VEGFA",
                baseline_readout=0.95,
                counterfactual_readout=1.4,
                fold_change=1.47,
                delta_absolute=0.45,
                horizon_min=15.0,
                narrative="Restoring EGFR capacity recovers VEGFA readout ~1.5× by 15 min.",
            )
        ],
        output_nodes=["VEGFA"],
        output_delta_sum=0.9,
        elapsed_ms=8.2,
        metadata={"method": "shap_ig_proxy"},
    )


def _mock_scientist() -> AIScientistReasoning:
    return AIScientistReasoning(
        brief=(
            "Resolved condition «Glioblastoma EGFR resistance»; clamp EGF=1.00: "
            "the Hill-cube network settled with Σy₆₀=12.40 across 12 nodes. "
            "Largest activity shifts (Δy₆₀): EGFR +0.600, BRAF +0.400. "
            "GAT attention re-routed: EGFR->BRAF strengthened (Δα=+0.120)."
        ),
        sentiment="up",
        total_flux_delta=0.35,
        top_node_deltas={"EGFR": 0.6, "BRAF": 0.4, "MAPK1": 0.35},
        attention_reroutes={"EGFR->BRAF": 0.12},
        perturbation_summary="KO=[] clamp={EGF:1.0} drug=[BRAF]",
        elapsed_ms=0.8,
        metadata={"generator": "filter_reasoner_v1"},
    )


def _mock_search_response() -> SearchAndSimulateResponse:
    """Assemble a full mocked successful search-and-simulate payload."""
    provenance = _mock_provenance()
    scrubber = _mock_scrubber(61)
    xai = _mock_xai()
    scientist = _mock_scientist()

    node_vectors = {
        "EGFR": NodeFeatureVector(
            y_init=0.2, y_final=0.8, delta_y=0.6, capacity=1.0, is_knocked_out=False
        ),
        "BRAF": NodeFeatureVector(
            y_init=0.3, y_final=0.7, delta_y=0.4, capacity=0.5, is_knocked_out=False
        ),
        "MAPK1": NodeFeatureVector(
            y_init=0.1, y_final=0.82, delta_y=0.72, capacity=1.0, is_knocked_out=False
        ),
        "VEGFA": NodeFeatureVector(
            y_init=0.05, y_final=0.95, delta_y=0.9, capacity=1.0, is_knocked_out=False
        ),
    }
    attention = {
        "EGFR->BRAF": 0.71,
        "BRAF->MAPK1": 0.66,
        "MAPK1->VEGFA": 0.58,
    }
    prioritization = PrioritizationResult(
        node_vectors=node_vectors,
        attention_matrix=attention,
        master_regulators=[("EGFR", 0.91), ("BRAF", 0.72), ("MAPK1", 0.61)],
        metadata={"n_nodes": 4},
    )
    path = CausalPathContext(
        nodes=["EGFR", "BRAF", "MAPK1", "VEGFA"],
        state_deltas={"EGFR": 0.6, "BRAF": 0.4, "MAPK1": 0.72, "VEGFA": 0.9},
        cumulative_attention=0.71 * 0.66 * 0.58,
        mechanisms=["phosphorylation", "phosphorylation", "transcription"],
        path_distance=1.2,
        edge_attentions=[0.71, 0.66, 0.58],
        signs=[1, 1, 1],
    )
    causal = ReasonResponse(
        context=CausalContextPayload(
            simulation_id=scrubber.simulation_id,
            extracted_paths=[path],
            top_master_regulator="EGFR",
            perturbed_nodes=["BRAF"],
            source_node="EGFR",
            target_node="VEGFA",
        ),
        brief="EGFR→BRAF→MAPK1→VEGFA cascade drives angiogenic readout.",
        prompt=None,
        elapsed_ms=4.0,
    )
    graph = PresetDetail(
        id="glioblastoma",
        name="Glioblastoma EGFR resistance",
        organism_id=9606,
        nodes={
            n: {"label": n, "y0": node_vectors[n].y_init}
            for n in node_vectors
        },
        edges=[
            {
                "source": "EGFR",
                "target": "BRAF",
                "sign": 1,
                "sources": ["omnipath", "reactome"],
            },
            {
                "source": "BRAF",
                "target": "MAPK1",
                "sign": 1,
                "sources": ["kegg", "string"],
            },
            {
                "source": "MAPK1",
                "target": "VEGFA",
                "sign": 1,
                "sources": ["local", "reactome"],
            },
        ],
        provenance=provenance.model_dump(),
    )

    return SearchAndSimulateResponse(
        query=provenance.query,
        profile_id=provenance.profile_id,
        resolved_graph=graph,
        scrubber_payload=scrubber,
        prioritization=prioritization,
        causal_brief=causal,
        xai_attributions=XAIAttributionResult.model_validate(xai.model_dump()),
        scientist_reasoning=ScientistReasoning.model_validate(scientist.model_dump()),
        topological_analysis=TopologicalAnalysis(
            bottlenecks=[],
            feedback_loops=[],
            synthetic_lethal_pairs=[],
            elapsed_ms=1.0,
        ),
        default_clamps={"EGF": 1.0},
        source_node="EGFR",
        target_node="VEGFA",
        resolve_ms=12.0,
        elapsed_ms=180.0,
        stages=[
            "Fetching multi-source topology",
            "Solving Hill-cube ODEs",
            "Calculating GAT Attention",
            "Computing XAI attributions",
            "Building BioReasoner Brief",
            "AI Scientist reasoning",
        ],
        metadata={"provenance": provenance.model_dump(), "n_nodes": 4, "n_edges": 3},
    )


# ---------------------------------------------------------------------------
# 1. Request schema contracts
# ---------------------------------------------------------------------------


def test_search_request_schema_required_fields() -> None:
    """POST body must accept the documented search-and-simulate fields."""
    req = SearchAndSimulateRequest(
        condition_query="Hypoxia-induced angiogenesis",
        selected_sources=["local", "omnipath", "reactome", "string"],
        custom_knockouts=["MTOR"],
        custom_clamps={"O2": 0.0},
        drug_perturbations=[
            DrugDoseRequest(target="BRAF", concentration=5.0, ki=1.0),
        ],
        use_omnipath=False,
    )
    assert isinstance(req.condition_query, str)
    assert isinstance(req.selected_sources, list)
    assert all(isinstance(s, str) for s in req.selected_sources)
    assert isinstance(req.custom_knockouts, list)
    assert isinstance(req.custom_clamps, dict)
    assert all(
        isinstance(k, str) and isinstance(v, float) for k, v in req.custom_clamps.items()
    )
    # Alias merges into drugs and clears drug_perturbations
    assert len(req.drugs) == 1
    assert req.drugs[0].target == "BRAF"
    assert req.drugs[0].c_drug == 5.0
    assert req.drug_perturbations == []


def test_search_request_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SearchAndSimulateRequest(
            condition_query="Hypoxia",
            not_a_real_field=True,  # type: ignore[call-arg]
        )


def test_search_request_json_roundtrip_contract() -> None:
    payload = {
        "condition_query": "Glioblastoma EGFR resistance",
        "selected_sources": ["local", "kegg", "string"],
        "custom_knockouts": ["EGFR"],
        "custom_clamps": {"EGF": 1.0},
        "drug_perturbations": [{"target": "BRAF", "concentration": 5.0, "ki": 1.0}],
    }
    req = SearchAndSimulateRequest.model_validate(payload)
    dumped = req.model_dump()
    assert dumped["condition_query"] == payload["condition_query"]
    assert dumped["selected_sources"] == payload["selected_sources"]
    assert dumped["custom_knockouts"] == ["EGFR"]
    assert dumped["custom_clamps"]["EGF"] == 1.0
    assert dumped["drugs"][0]["target"] == "BRAF"


# ---------------------------------------------------------------------------
# 2. Named contract models
# ---------------------------------------------------------------------------


def test_multisource_provenance_contract() -> None:
    prov = _mock_provenance()
    for src in ("omnipath", "reactome", "string"):
        assert src in prov.selected_sources
    assert prov.source_status["omnipath"] == "ok"
    again = MultiSourceProvenance.model_validate(prov.model_dump())
    assert again.builder == "resolve_multisource_network"
    assert set(prov.selected_sources) <= set(KNOWN_SOURCES)


def test_node_biophysics_5d_contract() -> None:
    bio = NodeBiophysics(
        gene_symbol="HIF1A",
        y_init=0.1,
        y_final=0.9,
        delta_y=0.8,
        capacity=1.0,
        is_knocked_out=False,
        uniprot_id="Q16665",
        localization="nucleus",
        shap_importance=0.44,
        shap_rank=2,
        feature_attributions=[
            {"feature_name": "delta_y", "value": 0.8, "attribution": 0.4},
        ],
    )
    vec = bio.as_5d()
    assert len(vec) == 5
    assert vec == [0.1, 0.9, 0.8, 1.0, 0.0]

    engine_vec = NodeFeatureVector(
        y_init=bio.y_init,
        y_final=bio.y_final,
        delta_y=bio.delta_y,
        capacity=bio.capacity,
        is_knocked_out=bio.is_knocked_out,
    )
    assert engine_vec.as_array() == vec

    inspector = NodeInspectorResponse(
        gene_symbol=bio.gene_symbol,
        uniprot_id=bio.uniprot_id,
        localization=bio.localization,
        y_init=bio.y_init,
        y_final=bio.y_final,
        delta_y=bio.delta_y,
        capacity=bio.capacity,
        shap_importance=bio.shap_importance,
        shap_rank=bio.shap_rank,
        feature_attributions=bio.feature_attributions,
    )
    assert inspector.gene_symbol == "HIF1A"


def test_xai_attributions_contract() -> None:
    xai = _mock_xai()
    assert xai.node_attributions
    top = xai.node_attributions[0]
    assert len(top.feature_attributions) == 5
    names = {f.feature_name for f in top.feature_attributions}
    assert {"y_init", "y_final", "delta_y", "capacity", "is_knocked_out"} <= names
    assert xai.counterfactuals
    assert xai.edge_flow_impacts[0].alpha == pytest.approx(0.71)

    prod = XAIAttributionResult.model_validate(xai.model_dump())
    assert prod.node_attributions[0].node == "EGFR"


def test_ai_scientist_reasoning_under_20ms_contract() -> None:
    sci = _mock_scientist()
    assert sci.brief
    assert len(sci.brief.split(".")) >= 2
    assert sci.elapsed_ms < 20.0
    assert sci.sentiment in {"up", "down", "mixed", "neutral"}
    assert sci.top_node_deltas

    prod = ScientistReasoning.model_validate(sci.model_dump())
    assert prod.elapsed_ms < 20.0


# ---------------------------------------------------------------------------
# 3. Mocked endpoint response structure
# ---------------------------------------------------------------------------


def test_mocked_search_and_simulate_response_structure() -> None:
    """Full mocked success body validates against SearchAndSimulateResponse."""
    resp = _mock_search_response()

    assert len(resp.scrubber_payload.time_steps) == 61
    for series in resp.scrubber_payload.nodes.values():
        assert len(series) == 61
    for series in resp.scrubber_payload.edges.values():
        assert len(series) == 61

    assert resp.prioritization.node_vectors
    for name, vec in resp.prioritization.node_vectors.items():
        assert len(vec.as_array()) == 5, name
    assert resp.prioritization.attention_matrix
    assert all("->" in k for k in resp.prioritization.attention_matrix)

    prov = MultiSourceProvenance.model_validate(resp.metadata["provenance"])
    assert "omnipath" in prov.selected_sources
    assert "reactome" in prov.selected_sources
    assert "string" in prov.selected_sources

    assert resp.xai_attributions is not None
    xai = XAIAttributions.model_validate(resp.xai_attributions.model_dump())
    assert xai.node_attributions[0].importance > 0
    assert xai.counterfactuals

    assert resp.scientist_reasoning is not None
    sci = AIScientistReasoning.model_validate(resp.scientist_reasoning.model_dump())
    assert sci.elapsed_ms < 20.0
    assert "Hill-cube" in sci.brief or "EGFR" in sci.brief

    wire = resp.model_dump(mode="json")
    again = SearchAndSimulateResponse.model_validate(wire)
    assert again.query == resp.query
    assert len(again.scrubber_payload.time_steps) == 61


def test_mocked_response_exposes_edge_source_badges() -> None:
    resp = _mock_search_response()
    tags = {
        src
        for e in resp.resolved_graph.edges
        for src in (e.get("sources") or [])
    }
    assert {"omnipath", "reactome", "string", "kegg", "local"} & tags


# ---------------------------------------------------------------------------
# 4. Live API smoke — schema keys only (offline local sources)
# ---------------------------------------------------------------------------


def test_live_search_and_simulate_schema_keys() -> None:
    """Real endpoint returns the contracted top-level keys."""
    with TestClient(create_app()) as client:
        r = client.post(
            "/api/v1/search-and-simulate",
            json={
                "condition_query": "Hypoxia-induced angiogenesis",
                "selected_sources": ["local", "uniprot"],
                "custom_knockouts": [],
                "custom_clamps": {"O2": 0.0},
                "drug_perturbations": [],
                "use_omnipath": False,
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()

        required = {
            "query",
            "profile_id",
            "resolved_graph",
            "scrubber_payload",
            "prioritization",
            "causal_brief",
            "xai_attributions",
            "scientist_reasoning",
            "default_clamps",
            "source_node",
            "target_node",
            "elapsed_ms",
            "stages",
            "metadata",
        }
        assert required <= set(body.keys())

        SearchAndSimulateResponse.model_validate(body)
        assert len(body["scrubber_payload"]["time_steps"]) == 61

        vectors = body["prioritization"]["node_vectors"]
        assert vectors
        sample = next(iter(vectors.values()))
        for key in ("y_init", "y_final", "delta_y", "capacity", "is_knocked_out"):
            assert key in sample

        xai = XAIAttributions.model_validate(body["xai_attributions"])
        assert xai.node_attributions

        sci = AIScientistReasoning.model_validate(body["scientist_reasoning"])
        assert sci.elapsed_ms < 20.0
        assert sci.brief

        prov_raw = body["metadata"].get("provenance") or body["resolved_graph"].get(
            "provenance"
        )
        assert prov_raw
        if "selected_sources" in prov_raw:
            MultiSourceProvenance.model_validate(
                {
                    "query": body["query"],
                    "profile_id": body["profile_id"],
                    **{
                        k: prov_raw[k]
                        for k in (
                            "selected_sources",
                            "source_status",
                            "n_edges_fused",
                            "n_nodes",
                            "builder",
                        )
                        if k in prov_raw
                    },
                }
            )
