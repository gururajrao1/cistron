"""
Cistron FastAPI REST gateway.

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

from fastapi import APIRouter, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import httpx

from cistron.ai import prioritize
from cistron.ai.scientist import generate_scientist_reasoning, snapshot_state_summary
from cistron.ai.xai import compute_xai_attributions
from cistron.math.topology import analyze_topology_vulnerabilities
from cistron.data import hypoxia_network_preset, offline_mapk_activity_graph
from cistron.data.multisource import (
    list_available_sources,
    list_source_situations,
)
from cistron.data.omics_parser import parse_omics_csv
from cistron.data.resolver import list_condition_suggestions, resolve_condition_network

from cistron.engine import DrugDose, HillCubeConfig, HillCubeEngine
from cistron.integrations.offline_data import OFFLINE_UNIPROT
from cistron.models.graph import (
    ActivityFlowEdge,
    CausalActivityGraph,
    GraphNode,
    MechanismKind,
)
from cistron.models.omics import OmicsProfile, calculate_alignment_score
from cistron.reasoner import (
    build_causal_context,
    generate_discovery_brief_prompt,
    synthesize_deterministic_brief,
)
from cistron.serialization import scrub_simulation

from cistron.api.schemas import (
    ConditionSuggestion,
    DynamicGraphSimulateRequest,
    HealthResponse,
    NodeInspectorResponse,
    OmicsSimulateRequest,
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
    y0: Optional[Dict[str, float]] = None,
):
    eng = HillCubeEngine(
        graph,
        config=HillCubeConfig(t_end=float(t_end), dense_output_points=int(dense_output_points)),
    )
    # Omics / custom baselines — soft initial conditions (ODE may evolve).
    if y0:
        for sym, val in y0.items():
            if sym in eng.symbols:
                eng.y0_override[sym] = min(1.0, max(0.0, float(val)))
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


def _execute_omics_simulate_pipeline(req: OmicsSimulateRequest) -> SearchAndSimulateResponse:
    """Hypoxia preset + omics-mapped y₀ baselines → full lab response."""
    t0 = time.perf_counter()
    stages: List[str] = []
    # Re-validate so sample/condition are normalized and provenance is dynamic.
    profile = OmicsProfile.model_validate(req.profile.model_dump())

    stages.append("Resolving local hypoxia preset graph")
    graph = hypoxia_network_preset()
    graph_id = f"omics_{profile.profile_id}"
    _DYNAMIC_GRAPHS[graph_id] = graph

    stages.append("Mapping omics log2_fc → y₀ baselines")
    # Soft clamps / initial activities — hard-clamping every node would freeze the ODE.
    baselines = profile.map_to_initial_states(
        list(graph.nodes.keys()),
        baseline_y0=float(req.baseline_y0),
        scaling_factor=float(req.scaling_factor),
    )
    # Measured features are held as clamps; unmapped nodes keep soft y₀ only.
    clamps = {
        sym: float(baselines[sym])
        for sym in profile.features
        if sym in baselines and sym in graph.nodes
    }
    # Interactive UI perturbations override omics clamps (0 = CRISPR KO).
    knockouts = list(req.knockouts)
    for sym, val in (req.perturbations or {}).items():
        if sym not in graph.nodes:
            continue
        clamps[sym] = float(val)
        if val <= 1e-6 and sym not in knockouts:
            knockouts.append(sym)

    source = req.source_node if req.source_node in graph.nodes else next(iter(graph.nodes), "O2")
    if "O2" in graph.nodes and req.source_node is None:
        source = "O2"
    target = req.target_node if req.target_node in graph.nodes else (
        "VEGFA" if "VEGFA" in graph.nodes else next(iter(graph.nodes), source)
    )

    stages.append("Solving Hill-cube ODEs")
    payload = _run_engine(
        graph,
        clamps=clamps,
        knockouts=knockouts,
        drugs=list(req.drugs),
        t_end=float(req.t_end),
        dense_output_points=int(req.dense_output_points),
        simulation_id=req.simulation_id or f"omics_{profile.profile_id}",
        meta_extra={
            "api": "omics-simulate",
            "omics_profile_id": profile.profile_id,
            "sample_name": profile.sample_name,
            "condition": profile.condition,
            "omics_provenance": profile.provenance,
            "graph_id": graph_id,
            "n_omics_features": len(profile.features),
            "n_omics_clamps": len(clamps),
            "perturbations": dict(req.perturbations or {}),
        },
        y0=baselines,
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
            "omics_profile_id": profile.profile_id,
            "condition": profile.condition,
            "sample_name": profile.sample_name,
            "knockouts": knockouts,
            "perturbations": dict(req.perturbations or {}),
            "clamps": clamps,
            "baselines": baselines,
            "drugs": [
                {"target": d.target, "c_drug": d.c_drug, "ki": d.ki} for d in req.drugs
            ],
        },
        prioritization=prio,
    )
    state_summary = snapshot_state_summary(
        payload,
        prio,
        knockouts=knockouts,
        clamps=clamps,
        condition_query=f"omics:{profile.condition}:{profile.sample_name}",
        scientist_brief=scientist.brief,
    )

    # Skip synthetic lethality unless Dual Screen requested.
    stages.append("Topological vulnerability analysis")
    want_sl = bool(getattr(req, "include_synthetic_lethality", False))
    focus = [str(s).strip().upper() for s in (req.sl_candidate_nodes or []) if str(s).strip()]
    topo = analyze_topology_vulnerabilities(
        graph,
        payload=payload,
        output_nodes=[target] if target in graph.nodes else None,
        top_bottlenecks=5,
        max_sl_candidates=6 if want_sl else 0,
        run_synthetic_lethality=want_sl,
        t_end=float(req.t_end),
        sl_time_budget_ms=450.0 if want_sl else 0.0,
        sl_candidate_nodes=focus or None,
    )

    stages.append("Scoring omics alignment (y₆₀ vs y₀)")
    steady = {
        sym: float(series[-1]) if series else 0.0
        for sym, series in (payload.nodes or {}).items()
    }
    align = calculate_alignment_score(
        steady,
        profile,
        baseline_y0=float(req.baseline_y0),
        scaling_factor=float(req.scaling_factor),
    )

    return SearchAndSimulateResponse(
        query=f"omics:{profile.condition}:{profile.sample_name}",
        profile_id=profile.profile_id,
        resolved_graph=_graph_to_detail(graph, graph_id=graph_id),
        scrubber_payload=payload,
        prioritization=prio,
        causal_brief=causal,
        xai_attributions=xai,
        scientist_reasoning=scientist,
        state_summary=state_summary,
        topological_analysis=topo,
        default_clamps=baselines,
        source_node=source,
        target_node=target,
        resolve_ms=(time.perf_counter() - t0) * 1000.0,
        elapsed_ms=(time.perf_counter() - t0) * 1000.0,
        stages=stages,
        alignment_score=float(align["alignment_score"]),
        omics_provenance=profile.provenance,
        metadata={
            "graph_id": graph_id,
            "omics_provenance": profile.provenance,
            "provenance": {
                "source": "omics_profile",
                "key": profile.provenance,
                "condition": profile.condition,
                "sample_name": profile.sample_name,
            },
            "n_nodes": len(graph.nodes),
            "n_edges": len(graph.edges),
            "n_omics_features": len(profile.features),
            "xai_ms": xai.elapsed_ms,
            "scientist_ms": scientist.elapsed_ms,
            "topology_ms": topo.elapsed_ms,
            "alignment_mse": align["mse"],
            "alignment_r2": align["r2"],
            "alignment_n": align["n_compared"],
        },
    )


def _execute_search_and_simulate_pipeline(req: SearchAndSimulateRequest) -> SearchAndSimulateResponse:
    t0 = time.perf_counter()
    stages: List[str] = []

    stages.append("Resolving condition network from query")
    # Interactive path: local curated profiles first; optional OmniPath enrich.
    use_omni = bool(getattr(req, "use_omnipath", True))
    # Offline-first when client only asked for local sources.
    sources = [str(s).lower() for s in (req.selected_sources or [])]
    if sources and "omnipath" not in sources and "signor" not in sources:
        use_omni = False
    resolved = resolve_condition_network(
        req.condition_query,
        use_omnipath=use_omni,
        omnipath_timeout=0.6,
    )
    graph = resolved.graph
    profile_id = resolved.profile_id
    graph_id = f"preset_{profile_id}_{abs(hash(req.condition_query)) % 10_000_000}"
    _DYNAMIC_GRAPHS[graph_id] = graph

    clamps = dict(resolved.default_clamps)
    if req.custom_clamps:
        clamps.update({k: float(v) for k, v in req.custom_clamps.items() if k in graph.nodes})

    # Drop clamps / KOs that are not in this scenario's topology.
    clamps = {k: v for k, v in clamps.items() if k in graph.nodes}
    knockouts = [k for k in req.custom_knockouts if k in graph.nodes]

    source = (
        req.source_node
        if req.source_node and req.source_node in graph.nodes
        else resolved.source_node
    )
    target = (
        req.target_node
        if req.target_node and req.target_node in graph.nodes
        else resolved.target_node
    )
    if source not in graph.nodes:
        source = next(iter(graph.nodes), resolved.source_node)
    if target not in graph.nodes:
        target = next(reversed(list(graph.nodes.keys())), resolved.target_node)

    stages.append(f"Solving Hill-cube ODEs ({profile_id})")
    payload = _run_engine(
        graph,
        clamps=clamps,
        knockouts=knockouts,
        drugs=[d for d in req.drugs if d.target in graph.nodes],
        t_end=float(req.t_end),
        dense_output_points=int(req.dense_output_points),
        simulation_id=req.simulation_id or f"search_{profile_id}",
        meta_extra={
            "condition_query": req.condition_query,
            "profile_id": profile_id,
            "graph_id": graph_id,
            "resolve_ms": resolved.resolve_ms,
            "provenance": dict(resolved.provenance or {}),
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
            "profile_id": profile_id,
            "knockouts": knockouts,
            "clamps": clamps,
            "drugs": [
                {"target": d.target, "c_drug": d.c_drug, "ki": d.ki}
                for d in req.drugs
                if d.target in graph.nodes
            ],
        },
        prioritization=prio,
    )
    state_summary = snapshot_state_summary(
        payload,
        prio,
        knockouts=knockouts,
        clamps=clamps,
        condition_query=req.condition_query,
        scientist_brief=scientist.brief,
    )

    stages.append("Topological vulnerability analysis")
    want_sl = bool(getattr(req, "include_synthetic_lethality", False))
    focus = [
        str(s).strip().upper()
        for s in (req.sl_candidate_nodes or [])
        if str(s).strip() and str(s).strip().upper() in graph.nodes
    ]
    topo = analyze_topology_vulnerabilities(
        graph,
        payload=payload,
        output_nodes=[target] if target in graph.nodes else None,
        top_bottlenecks=5,
        max_sl_candidates=6 if want_sl else 0,
        run_synthetic_lethality=want_sl,
        t_end=float(req.t_end),
        sl_time_budget_ms=450.0 if want_sl else 0.0,
        sl_candidate_nodes=focus or None,
    )

    return SearchAndSimulateResponse(
        query=req.condition_query,
        profile_id=profile_id,
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
        resolve_ms=float(resolved.resolve_ms),
        elapsed_ms=(time.perf_counter() - t0) * 1000.0,
        stages=stages,
        metadata={
            "graph_id": graph_id,
            "profile_id": profile_id,
            "provenance": dict(resolved.provenance or {"source": "condition_resolver"}),
            "n_nodes": len(graph.nodes),
            "n_edges": len(graph.edges),
            "xai_ms": xai.elapsed_ms,
            "scientist_ms": scientist.elapsed_ms,
            "topology_ms": topo.elapsed_ms,
        },
    )


def _topology_to_causal(req: DynamicGraphSimulateRequest) -> CausalActivityGraph:
    """Convert Reactome+STRING Cytoscape payload → CausalActivityGraph."""
    nodes: Dict[str, GraphNode] = {}
    for n in req.nodes:
        sym = str(n.symbol or n.id).strip().upper()
        if not sym or sym in nodes:
            continue
        nodes[sym] = GraphNode(
            gene_symbol=sym,
            tau_min=1.0,
            activity_weight=1.0,
            initial_concentration=float(n.y0),
            metadata={"source": "reactome_string"},
        )

    edges: List[ActivityFlowEdge] = []
    seen: set[tuple[str, str, int]] = set()
    for e in req.edges:
        src = str(e.source).strip().upper()
        tgt = str(e.target).strip().upper()
        if not src or not tgt or src == tgt:
            continue
        if src not in nodes or tgt not in nodes:
            continue
        et = str(e.type or "activation").strip().lower()
        inhib = et in {"inhibition", "inhibitory", "repression", "negative"}
        sign = -1 if inhib else 1
        key = (src, tgt, sign)
        if key in seen:
            continue
        seen.add(key)
        w = float(e.weight)
        if w > 1.0:
            w = w / 1000.0
        w = max(0.0, min(1.0, w))
        edges.append(
            ActivityFlowEdge(
                source=src,
                target=tgt,
                sign=sign,  # type: ignore[arg-type]
                is_stimulation=not inhib,
                is_inhibition=inhib,
                mechanism=MechanismKind.ENZYMATIC,
                sources=["STRING", "Reactome"],
                datasets=["string-db", "reactome"],
                evidence_score=w,
                metadata={"string_weight": w, "edge_type": et},
            )
        )

    if len(nodes) < 2:
        raise ValueError("Dynamic topology needs at least 2 nodes")
    if not edges:
        # Fully disconnected — add a soft chain so the ODE still has structure.
        ordered = list(nodes.keys())
        for i in range(len(ordered) - 1):
            edges.append(
                ActivityFlowEdge(
                    source=ordered[i],
                    target=ordered[i + 1],
                    sign=1,
                    is_stimulation=True,
                    is_inhibition=False,
                    mechanism=MechanismKind.ENZYMATIC,
                    sources=["synthetic"],
                    evidence_score=0.4,
                )
            )

    profile = str(req.profile_id).strip() or "cistron-dynamic"
    return CausalActivityGraph(
        name=str(req.pathway_name or req.query).strip() or profile,
        organism_id=9606,
        nodes=nodes,
        edges=edges,
        provenance={
            "source": "reactome_string_dynamic",
            "profile_id": profile,
            "pathway_id": req.pathway_id,
            "pathway_name": req.pathway_name,
            "query": req.query,
            "n_nodes": len(nodes),
            "n_edges": len(edges),
        },
    )


def _execute_dynamic_graph_pipeline(req: DynamicGraphSimulateRequest) -> SearchAndSimulateResponse:
    """Hill-cube + GAT/XAI/BioReasoner for a client-built Reactome/STRING graph."""
    t0 = time.perf_counter()
    stages: List[str] = ["Constructing dynamic interactome from Reactome & STRING-DB"]

    graph = _topology_to_causal(req)
    profile_id = str(req.profile_id).strip() or "cistron-dynamic"
    graph_id = f"dynamic_{profile_id}_{abs(hash(req.query)) % 10_000_000}"
    _DYNAMIC_GRAPHS[graph_id] = graph

    # Soft y₀ from client nodes; optional clamps / KOs.
    y0 = {
        sym: float(n.initial_concentration)
        for sym, n in graph.nodes.items()
    }
    clamps = {
        k: float(v)
        for k, v in (req.custom_clamps or {}).items()
        if k in graph.nodes
    }
    knockouts = [k for k in req.custom_knockouts if k in graph.nodes]

    symbols = list(graph.nodes.keys())
    source = (
        req.source_node
        if req.source_node and req.source_node in graph.nodes
        else symbols[0]
    )
    target = (
        req.target_node
        if req.target_node and req.target_node in graph.nodes
        else symbols[-1]
    )

    stages.append(f"Solving Hill-cube ODEs ({profile_id})")
    payload = _run_engine(
        graph,
        clamps=clamps,
        knockouts=knockouts,
        drugs=[d for d in req.drugs if d.target in graph.nodes],
        t_end=float(req.t_end),
        dense_output_points=int(req.dense_output_points),
        simulation_id=req.simulation_id or f"dyn_{profile_id}",
        y0=y0,
        meta_extra={
            "condition_query": req.query,
            "profile_id": profile_id,
            "graph_id": graph_id,
            "pathway_id": req.pathway_id,
            "provenance": dict(graph.provenance or {}),
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
    causal = ReasonResponse(
        context=context,
        brief=synthesize_deterministic_brief(context),
        prompt=generate_discovery_brief_prompt(context),
        prioritization=None,
        elapsed_ms=0.0,
    )

    stages.append("AI Scientist reasoning")
    scientist = generate_scientist_reasoning(
        req.previous_state_summary,
        payload,
        perturbation_delta={
            "condition_query": req.query,
            "profile_id": profile_id,
            "pathway_id": req.pathway_id,
            "knockouts": knockouts,
            "clamps": clamps,
        },
        prioritization=prio,
    )
    state_summary = snapshot_state_summary(
        payload,
        prio,
        knockouts=knockouts,
        clamps=clamps,
        condition_query=req.query,
        scientist_brief=scientist.brief,
    )

    stages.append("Topological vulnerability analysis")
    want_sl = bool(req.include_synthetic_lethality)
    focus = [
        str(s).strip().upper()
        for s in (req.sl_candidate_nodes or [])
        if str(s).strip() and str(s).strip().upper() in graph.nodes
    ]
    topo = analyze_topology_vulnerabilities(
        graph,
        payload=payload,
        output_nodes=[target] if target in graph.nodes else None,
        top_bottlenecks=5,
        max_sl_candidates=6 if want_sl else 0,
        run_synthetic_lethality=want_sl,
        t_end=float(req.t_end),
        sl_time_budget_ms=450.0 if want_sl else 0.0,
        sl_candidate_nodes=focus or None,
    )

    return SearchAndSimulateResponse(
        query=req.query,
        profile_id=profile_id,
        resolved_graph=_graph_to_detail(graph, graph_id=graph_id),
        scrubber_payload=payload,
        prioritization=prio,
        causal_brief=causal,
        xai_attributions=xai,
        scientist_reasoning=scientist,
        state_summary=state_summary,
        topological_analysis=topo,
        default_clamps=clamps or {source: float(y0.get(source, 0.5))},
        source_node=source,
        target_node=target,
        resolve_ms=0.0,
        elapsed_ms=(time.perf_counter() - t0) * 1000.0,
        stages=stages,
        metadata={
            "graph_id": graph_id,
            "profile_id": profile_id,
            "provenance": dict(graph.provenance or {}),
            "pathway_id": req.pathway_id,
            "n_nodes": len(graph.nodes),
            "n_edges": len(graph.edges),
            "xai_ms": xai.elapsed_ms,
            "scientist_ms": scientist.elapsed_ms,
            "topology_ms": topo.elapsed_ms,
            "source": "reactome_string_dynamic",
        },
    )


def _register_routes(router: APIRouter) -> None:
    @router.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            service="cistron-api",
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

    @router.get("/sources", tags=["search"])
    def knowledge_sources() -> List[Dict[str, str]]:
        """Explorer catalogue — local, OmniPath, SIGNOR, KEGG, Reactome, STRING, BioGRID, UniProt."""
        return list_available_sources()

    @router.get("/situations", tags=["search"])
    def source_situations(
        sources: Optional[str] = Query(
            default=None,
            description="Comma-separated source ids (e.g. local,omnipath,kegg)",
        ),
    ) -> List[Dict[str, str]]:
        """Curated situations for the Explorer dropdown, filtered by enabled sources."""
        selected = (
            [s.strip() for s in sources.split(",") if s.strip()] if sources else None
        )
        return list_source_situations(selected)

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

    @router.post(
        "/simulate-dynamic-graph",
        response_model=SearchAndSimulateResponse,
        tags=["search"],
        summary="Simulate a Reactome+STRING interactome built in the browser",
    )
    async def simulate_dynamic_graph(
        req: DynamicGraphSimulateRequest,
    ) -> SearchAndSimulateResponse:
        if len(req.nodes) < 2:
            raise HTTPException(status_code=422, detail="Need at least 2 topology nodes")
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(_execute_dynamic_graph_pipeline, req),
                timeout=8.0,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except asyncio.TimeoutError:
            raise HTTPException(
                status_code=504,
                detail="Dynamic graph simulation timed out",
            ) from None
        except Exception as exc:
            logger.exception("simulate-dynamic-graph failed")
            raise HTTPException(
                status_code=500,
                detail=f"simulate-dynamic-graph failed ({type(exc).__name__}): {exc}",
            ) from exc

    @router.post(
        "/omics/upload",
        response_model=OmicsProfile,
        tags=["omics"],
        summary="Upload differential-omics CSV → OmicsProfile",
    )
    async def omics_upload(
        file: UploadFile = File(..., description="CSV/TSV differential expression table"),
        sample_name: str = Form(default="Sample_01"),
        condition: str = Form(default="Experimental"),
    ) -> OmicsProfile:
        raw = await file.read()
        if not raw:
            raise HTTPException(status_code=422, detail="Uploaded file is empty")
        try:
            # OmicsProfile validators normalize labels + compute cistron-{slug} provenance.
            return parse_omics_csv(raw, sample_name=sample_name, condition=condition)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("omics upload parse failed")
            raise HTTPException(
                status_code=422,
                detail=f"Invalid omics CSV ({type(exc).__name__}): {exc}",
            ) from exc

    @router.post(
        "/omics/simulate",
        response_model=SearchAndSimulateResponse,
        tags=["omics"],
        summary="Omics-conditioned Hill-cube simulate + GAT/XAI/BioReasoner",
    )
    async def omics_simulate(req: OmicsSimulateRequest) -> SearchAndSimulateResponse:
        if not req.profile.features:
            raise HTTPException(status_code=422, detail="OmicsProfile.features is empty")
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(_execute_omics_simulate_pipeline, req),
                timeout=4.0,
            )
        except asyncio.TimeoutError:
            raise HTTPException(
                status_code=504,
                detail="omics/simulate timed out",
            ) from None
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("omics/simulate failed")
            raise HTTPException(
                status_code=500,
                detail=f"omics/simulate failed ({type(exc).__name__}): {exc}",
            ) from exc


def create_app() -> FastAPI:
    app = FastAPI(title="Cistron API", version="0.22.0")
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

    # Browser CORS bypass for Reactome / STRING (used by production SPA).
    @app.api_route("/proxy/reactome/{path:path}", methods=["GET", "POST", "OPTIONS"])
    async def proxy_reactome(path: str, request: Request) -> Response:
        return await _proxy_upstream(f"https://reactome.org/{path}", request)

    @app.api_route("/proxy/string-db/{path:path}", methods=["GET", "POST", "OPTIONS"])
    async def proxy_string(path: str, request: Request) -> Response:
        return await _proxy_upstream(f"https://string-db.org/{path}", request)

    # Optional: serve Vite build from the same process (Render / Docker free deploy).
    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist.is_dir():
        assets = dist / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str):
            if full_path.startswith(("api/", "proxy/", "health", "presets", "simulate")):
                raise HTTPException(status_code=404, detail="Not found")
            index = dist / "index.html"
            if not index.is_file():
                raise HTTPException(status_code=404, detail="Frontend not built")
            return Response(index.read_bytes(), media_type="text/html")

    return app


async def _proxy_upstream(url: str, request: Request) -> Response:
    if request.method == "OPTIONS":
        return Response(status_code=204)
    q = str(request.url.query)
    target = f"{url}?{q}" if q else url
    body = await request.body()
    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in {"host", "content-length", "connection"}
    }
    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            upstream = await client.request(
                request.method,
                target,
                content=body if body else None,
                headers=headers,
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Upstream proxy error: {exc}") from exc
    excluded = {"content-encoding", "transfer-encoding", "content-length", "connection"}
    out_headers = {
        k: v for k, v in upstream.headers.items() if k.lower() not in excluded
    }
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=out_headers,
        media_type=upstream.headers.get("content-type"),
    )


app = create_app()
