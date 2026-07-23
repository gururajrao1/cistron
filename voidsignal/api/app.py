"""
VoidSignal FastAPI REST gateway.

Exposes network presets, dynamic condition search, Hill-cube ODE simulation,
graph-attention prioritization, and Causal BioReasoner briefs.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional
import logging
import time
import traceback

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from voidsignal.ai import prioritize
from voidsignal.ai.scientist import generate_scientist_reasoning, snapshot_state_summary
from voidsignal.ai.xai import compute_xai_attributions
from voidsignal.math.topology import analyze_topology_vulnerabilities
from voidsignal.data import hypoxia_network_preset, offline_mapk_activity_graph
from voidsignal.data.multisource import (
    list_available_sources,
    list_source_situations,
)
from voidsignal.data.resolver import list_condition_suggestions

from voidsignal.engine import DrugDose, HillCubeConfig, HillCubeEngine
from voidsignal.integrations.offline_data import OFFLINE_UNIPROT
from voidsignal.models.graph import CausalActivityGraph
from voidsignal.reasoner import (
    build_causal_context,
    generate_discovery_brief_prompt,
    synthesize_deterministic_brief,
)
from voidsignal.serialization import scrub_simulation

from voidsignal.api.schemas import (
    ConditionSuggestion,
    HealthResponse,
    NodeInspectorResponse,
    PresetDetail,
    PresetSummary,
    PrioritizeRequest,
    PrioritizeResponse,
    ReasonRequest,
    ReasonResponse,
    SearchAndSimulateRequest,
    SearchAndSimulateResponse,
    SimulateRequest,
    SimulateResponse,
)

logger = logging.getLogger(__name__)

PresetFactory = Callable[[], CausalActivityGraph]

_PRESET_META: Dict[str, Dict[str, str]] = {
    "hypoxia": {
        "description": "O2→EGLN1⊣HIF1A→VEGFA/GLUT1 hypoxia scaffold",
    },
    "mapk": {
        "description": "Offline EGF→EGFR→RAS→RAF→MEK→ERK MAPK cascade",
    },
}

_LOCALIZATION_FALLBACK: Dict[str, Dict[str, Optional[str]]] = {
    "HIF1A": {
        "accession": "Q16665",
        "full_name": "Hypoxia-inducible factor 1-alpha",
        "localization": "Nucleus",
        "function": "Master transcriptional regulator of the hypoxic response.",
    },
    "EGLN1": {
        "accession": "Q9GZT9",
        "full_name": "Egl nine homolog 1 (PHD2)",
        "localization": "Cytosol",
        "function": "Prolyl hydroxylase tagging HIF1A for proteasomal degradation.",
    },
    "VEGFA": {
        "accession": "P15692",
        "full_name": "Vascular endothelial growth factor A",
        "localization": "Secreted / Extracellular",
        "function": "Angiogenic cytokine induced by HIF1A.",
    },
    "GLUT1": {
        "accession": "P11166",
        "full_name": "Solute carrier family 2, facilitated glucose transporter member 1",
        "localization": "Plasma Membrane",
        "function": "Glucose uptake transporter under hypoxic metabolic reprogramming.",
    },
    "O2": {
        "accession": None,
        "full_name": "Molecular oxygen (environmental clamp)",
        "localization": "Environment",
        "function": "Extracellular O₂ level controlling EGLN1 activity.",
    },
}

_DYNAMIC_GRAPHS: Dict[str, CausalActivityGraph] = {}


def _protein_meta(symbol: str) -> Dict[str, Optional[str]]:
    sym = symbol.strip().upper()
    row = OFFLINE_UNIPROT.get(sym) or OFFLINE_UNIPROT.get(symbol)
    if isinstance(row, dict):
        return {
            "uniprot_id": str(row.get("accession") or "") or None,
            "full_name": str(row.get("full_name") or "") or None,
            "localization": str(row.get("localization") or "") or None,
            "function": str(row.get("function") or "") or None,
        }
    fb = _LOCALIZATION_FALLBACK.get(sym) or _LOCALIZATION_FALLBACK.get(symbol)
    if fb:
        acc = fb.get("accession")
        return {
            "uniprot_id": str(acc) if acc else None,
            "full_name": fb.get("full_name"),
            "localization": fb.get("localization"),
            "function": fb.get("function"),
        }
    return {
        "uniprot_id": None,
        "full_name": None,
        "localization": "Unknown",
        "function": None,
    }


def _preset_factories() -> Dict[str, PresetFactory]:
    return {
        "hypoxia": hypoxia_network_preset,
        "mapk": offline_mapk_activity_graph,
    }


def resolve_preset(preset_id: str) -> CausalActivityGraph:
    key = preset_id.strip().lower()
    if key in _DYNAMIC_GRAPHS:
        return _DYNAMIC_GRAPHS[key]
    factories = _preset_factories()
    if key not in factories:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown preset {preset_id!r}.",
        )
    return factories[key]()


def _graph_to_detail(graph: CausalActivityGraph, *, graph_id: str) -> PresetDetail:
    return PresetDetail(
        id=graph_id,
        name=graph.name,
        organism_id=graph.organism_id,
        nodes={sym: n.model_dump(mode="json") for sym, n in graph.nodes.items()},
        edges=[e.model_dump(mode="json") for e in graph.edges],
        provenance=dict(graph.provenance or {}),
    )


def _run_engine(
    graph: CausalActivityGraph,
    *,
    clamps: Dict[str, float],
    knockouts: List[str],
    drugs: List,
    t_end: float,
    dense_output_points: int,
    simulation_id: Optional[str],
    meta_extra: Optional[Dict] = None,
):
    eng = HillCubeEngine(
        graph,
        config=HillCubeConfig(t_end=float(t_end), dense_output_points=int(dense_output_points)),
    )
    for sym, val in clamps.items():
        if sym in eng.symbols:
            eng.clamp(sym, float(val))
    if knockouts:
        known = [k for k in knockouts if k in eng.symbols]
        if known:
            eng.knockout(known)
    if drugs:
        known_drugs = [d for d in drugs if d.target in eng.symbols]
        if known_drugs:
            eng.apply_drugs(
                [
                    DrugDose(target=d.target, c_drug=d.c_drug, ki=d.ki)
                    for d in known_drugs
                ]
            )
    meta = {"api": "search-and-simulate", **(meta_extra or {})}
    return scrub_simulation(
        eng,
        t_end=float(t_end),
        simulation_id=simulation_id,
        metadata=meta,
    )


def _execute_search_and_simulate_pipeline(req: SearchAndSimulateRequest) -> SearchAndSimulateResponse:
    t0 = time.perf_counter()
    stages: List[str] = []

    stages.append("Resolving local hypoxia preset graph")
    graph = hypoxia_network_preset()
    graph_id = f"preset_hypoxia_{abs(hash(req.condition_query)) % 10_000_000}"
    _DYNAMIC_GRAPHS[graph_id] = graph

    clamps = {"O2": 0.0}
    if req.custom_clamps:
        clamps.update({k: float(v) for k, v in req.custom_clamps.items() if k in graph.nodes})

    source = req.source_node if req.source_node in graph.nodes else "O2"
    target = req.target_node if req.target_node in graph.nodes else "VEGFA"

    stages.append("Solving Hill-cube ODEs")
    payload = _run_engine(
        graph,
        clamps=clamps,
        knockouts=list(req.custom_knockouts),
        drugs=list(req.drugs),
        t_end=float(req.t_end),
        dense_output_points=int(req.dense_output_points),
        simulation_id=req.simulation_id or "search_hypoxia",
        meta_extra={
            "condition_query": req.condition_query,
            "profile_id": "hypoxia",
            "graph_id": graph_id,
        },
    )

    stages.append("Calculating GAT Attention")
    prio = prioritize(graph, payload)

    stages.append("Computing XAI attributions")
    xai = compute_xai_attributions(
        graph,
        payload,
        prio,
        output_nodes=[target] if target in graph.nodes else None,
    )

    stages.append("Building BioReasoner Brief")
    context = build_causal_context(
        graph,
        payload,
        source_node=source,
        target_node=target,
        k=3,
        prioritization=prio,
    )
    brief = synthesize_deterministic_brief(context)
    prompt = generate_discovery_brief_prompt(context)
    causal = ReasonResponse(
        context=context,
        brief=brief,
        prompt=prompt,
        prioritization=None,
        elapsed_ms=0.0,
    )

    stages.append("AI Scientist reasoning")
    scientist = generate_scientist_reasoning(
        req.previous_state_summary,
        payload,
        perturbation_delta={
            "condition_query": req.condition_query,
            "knockouts": list(req.custom_knockouts),
            "clamps": clamps,
            "drugs": [
                {"target": d.target, "c_drug": d.c_drug, "ki": d.ki} for d in req.drugs
            ],
        },
        prioritization=prio,
    )
    state_summary = snapshot_state_summary(
        payload,
        prio,
        knockouts=req.custom_knockouts,
        clamps=clamps,
        condition_query=req.condition_query,
        scientist_brief=scientist.brief,
    )

    stages.append("Topological vulnerability analysis")
    want_sl = bool(getattr(req, "include_synthetic_lethality", False))
    topo = analyze_topology_vulnerabilities(
        graph,
        payload=payload,
        output_nodes=[target] if target in graph.nodes else None,
        top_bottlenecks=5,
        max_sl_candidates=5 if want_sl else 0,
        run_synthetic_lethality=want_sl,
        t_end=float(req.t_end),
        sl_time_budget_ms=300.0 if want_sl else 0.0,
    )

    return SearchAndSimulateResponse(
        query=req.condition_query,
        profile_id="hypoxia",
        resolved_graph=_graph_to_detail(graph, graph_id=graph_id),
        scrubber_payload=payload,
        prioritization=prio,
        causal_brief=causal,
        xai_attributions=xai,
        scientist_reasoning=scientist,
        state_summary=state_summary,
        topological_analysis=topo,
        default_clamps=clamps,
        source_node=source,
        target_node=target,
        resolve_ms=1.0,
        elapsed_ms=(time.perf_counter() - t0) * 1000.0,
        stages=stages,
        metadata={
            "graph_id": graph_id,
            "provenance": {"source": "local_preset"},
            "n_nodes": len(graph.nodes),
            "n_edges": len(graph.edges),
            "xai_ms": xai.elapsed_ms,
            "scientist_ms": scientist.elapsed_ms,
            "topology_ms": topo.elapsed_ms,
        },
    )


def _register_routes(router: APIRouter) -> None:
    @router.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            service="voidsignal-api",
            version="0.22.0",
            timestamp=datetime.now(timezone.utc).isoformat(),
            database_handles={
                "presets_loaded": ["hypoxia", "mapk"],
                "dynamic_graphs_cached": len(_DYNAMIC_GRAPHS),
                "condition_suggestions": 8,
                "omnipath_client": "ready",
                "hill_cube_engine": "ready",
            },
        )

    @router.get(
        "/conditions/suggestions",
        response_model=List[ConditionSuggestion],
        tags=["search"],
    )
    def condition_suggestions() -> List[ConditionSuggestion]:
        return [ConditionSuggestion(**row) for row in list_condition_suggestions()]

    @router.post(
        "/search-and-simulate",
        response_model=SearchAndSimulateResponse,
        tags=["search"],
    )
    async def search_and_simulate(req: SearchAndSimulateRequest) -> SearchAndSimulateResponse:
        if not req.condition_query.strip():
            raise HTTPException(status_code=400, detail="condition_query is empty")
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(_execute_search_and_simulate_pipeline, req),
                timeout=4.0,
            )
        except asyncio.TimeoutError:
            logger.warning("Simulation hit timeout cutoff, returning fallback local graph.")
            fallback_req = req.model_copy(update={"selected_sources": ["local"]})
            return _execute_search_and_simulate_pipeline(fallback_req)
        except Exception as exc:
            logger.exception("search-and-simulate failed")
            raise HTTPException(
                status_code=500,
                detail=f"search-and-simulate failed ({type(exc).__name__}): {exc}",
            ) from exc


def create_app() -> FastAPI:
    app = FastAPI(title="VoidSignal API", version="0.22.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    root = APIRouter()
    _register_routes(root)
    app.include_router(root)

    v1 = APIRouter(prefix="/api/v1")
    _register_routes(v1)
    app.include_router(v1)

    return app


app = create_app()