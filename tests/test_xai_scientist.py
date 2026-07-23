"""Tests for XAI attributions and AI Scientist live reasoning."""

from __future__ import annotations

import time

import pytest

from voidsignal.ai.scientist import generate_scientist_reasoning, snapshot_state_summary
from voidsignal.ai.xai import compute_xai_attributions
from voidsignal.ai import prioritize
from voidsignal.data.resolver import resolve_condition_network
from voidsignal.engine import HillCubeConfig, HillCubeEngine
from voidsignal.serialization import scrub_simulation

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from voidsignal.api.app import create_app


def _hypoxia_run():
    resolved = resolve_condition_network("Hypoxia", use_omnipath=False)
    eng = HillCubeEngine(
        resolved.graph,
        config=HillCubeConfig(t_end=60.0, dense_output_points=61),
    )
    eng.clamp("O2", 0.0)
    payload = scrub_simulation(eng, t_end=60.0, simulation_id="xai_test")
    prio = prioritize(resolved.graph, payload)
    return resolved.graph, payload, prio


def test_xai_attributions_fast() -> None:
    graph, payload, prio = _hypoxia_run()
    t0 = time.perf_counter()
    xai = compute_xai_attributions(graph, payload, prio)
    elapsed = (time.perf_counter() - t0) * 1000.0
    assert elapsed < 50.0
    assert xai.node_attributions
    assert xai.edge_flow_impacts
    assert xai.counterfactuals
    assert xai.elapsed_ms < 50.0
    top = xai.node_attributions[0]
    assert top.feature_attributions
    assert any(f.feature_name == "delta_y" for f in top.feature_attributions)


def test_scientist_under_20ms() -> None:
    graph, payload, prio = _hypoxia_run()
    prev = snapshot_state_summary(payload, prio, clamps={"O2": 0.0})
    # Second run with knockout
    eng = HillCubeEngine(graph, config=HillCubeConfig(t_end=60.0, dense_output_points=61))
    eng.clamp("O2", 0.0)
    eng.knockout(["MTOR"])
    payload2 = scrub_simulation(eng, t_end=60.0, simulation_id="xai_ko")
    prio2 = prioritize(graph, payload2)

    t0 = time.perf_counter()
    reasoning = generate_scientist_reasoning(
        prev,
        payload2,
        perturbation_delta={"knockouts": ["MTOR"], "clamps": {"O2": 0.0}},
        prioritization=prio2,
    )
    wall = (time.perf_counter() - t0) * 1000.0
    assert wall < 20.0
    assert reasoning.elapsed_ms < 20.0
    assert len(reasoning.brief.split(".")) >= 2
    assert reasoning.sentiment in {"up", "down", "mixed", "neutral"}


def test_search_returns_xai_and_scientist() -> None:
    with TestClient(create_app()) as client:
        r = client.post(
            "/api/v1/search-and-simulate",
            json={
                "condition_query": "Glioblastoma EGFR resistance",
                "custom_knockouts": ["EGFR"],
                "custom_clamps": {"EGF": 1.0},
                "drug_perturbations": [
                    {"target": "BRAF", "concentration": 5.0, "ki": 1.0}
                ],
                "use_omnipath": False,
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["xai_attributions"]["node_attributions"]
        assert body["scientist_reasoning"]["brief"]
        assert body["scientist_reasoning"]["elapsed_ms"] < 20.0
        assert body["state_summary"]["node_finals"]
        assert body["elapsed_ms"] < 2000.0
        assert body["scrubber_payload"]["nodes"]["EGFR"][-1] == 0.0


def test_protein_card() -> None:
    with TestClient(create_app()) as client:
        r = client.get("/api/v1/proteins/HIF1A")
        assert r.status_code == 200
        body = r.json()
        assert body["gene_symbol"] == "HIF1A"
        assert body["localization"]
        assert body["uniprot_id"]
