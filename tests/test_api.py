"""FastAPI gateway tests — live routes only (search-and-simulate / health / proteins)."""

from __future__ import annotations

import time

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from cistron.api.app import create_app

LATENCY_BUDGET_MS = 2000.0


@pytest.fixture(scope="module")
def client() -> TestClient:
    app = create_app()
    with TestClient(app) as c:
        c.get("/health")
        c.post(
            "/api/v1/search-and-simulate",
            json={
                "condition_query": "Hypoxia-induced angiogenesis",
                "use_omnipath": False,
                "selected_sources": ["local"],
            },
        )
        yield c


def test_health(client: TestClient) -> None:
    t0 = time.perf_counter()
    r = client.get("/health")
    elapsed = (time.perf_counter() - t0) * 1000.0
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "timestamp" in body
    assert "database_handles" in body
    assert "spa_built" in body["database_handles"]
    assert elapsed < LATENCY_BUDGET_MS


def test_search_and_simulate_hypoxia(client: TestClient) -> None:
    t0 = time.perf_counter()
    r = client.post(
        "/api/v1/search-and-simulate",
        json={
            "condition_query": "Hypoxia-induced angiogenesis",
            "custom_knockouts": [],
            "custom_clamps": {},
            "use_omnipath": False,
            "selected_sources": ["local"],
        },
    )
    elapsed = (time.perf_counter() - t0) * 1000.0
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["profile_id"] == "hypoxia"
    assert "HIF1A" in body["scrubber_payload"]["nodes"]
    assert body["metadata"].get("sim_id")
    assert body["metadata"].get("synthetic_edges") is False
    assert elapsed < LATENCY_BUDGET_MS


def test_unmatched_condition_422(client: TestClient) -> None:
    r = client.post(
        "/api/v1/search-and-simulate",
        json={
            "condition_query": "kuru prion nonsense xyzzy",
            "use_omnipath": False,
            "selected_sources": ["local"],
        },
    )
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert isinstance(detail, dict)
    assert detail.get("code") == "unmatched_condition"
    assert detail.get("suggestions")


def test_dynamic_graph_no_synthetic_edges(client: TestClient) -> None:
    r = client.post(
        "/api/v1/simulate-dynamic-graph",
        json={
            "query": "disconnected demo",
            "profile_id": "cistron-test-disconnected",
            "nodes": [
                {"id": "AAA", "symbol": "AAA", "y0": 0.5},
                {"id": "BBB", "symbol": "BBB", "y0": 0.5},
            ],
            "edges": [],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["resolved_graph"]["edges"]) == 0
    assert body["metadata"].get("synthetic_edges") is False
    assert "AAA" in body["scrubber_payload"]["nodes"]
    assert "BBB" in body["scrubber_payload"]["nodes"]


def test_omics_requires_active_graph(client: TestClient) -> None:
    r = client.post(
        "/api/v1/omics/simulate",
        json={
            "profile": {
                "profile_id": "test",
                "sample_name": "S1",
                "condition": "Experimental",
                "features": {
                    "HIF1A": {"symbol": "HIF1A", "log2_fc": 2.0},
                },
            }
        },
    )
    assert r.status_code == 422, r.text
    assert "NO_ACTIVE_GRAPH" in r.json()["detail"]


def test_omics_on_active_graph(client: TestClient) -> None:
    sim = client.post(
        "/api/v1/search-and-simulate",
        json={
            "condition_query": "Hypoxia",
            "use_omnipath": False,
            "selected_sources": ["local"],
        },
    )
    assert sim.status_code == 200, sim.text
    graph_id = sim.json()["metadata"]["graph_id"]
    r = client.post(
        "/api/v1/omics/simulate",
        json={
            "graph_id": graph_id,
            "profile": {
                "profile_id": "omics-hyp",
                "sample_name": "S1",
                "condition": "Hypoxia RNA",
                "features": {
                    "HIF1A": {"symbol": "HIF1A", "log2_fc": 2.4},
                    "NOTINGRAPH": {"symbol": "NOTINGRAPH", "log2_fc": 1.0},
                },
            },
        },
    )
    assert r.status_code == 200, r.text
    meta = r.json()["metadata"]
    assert "HIF1A" in meta.get("omics_mapped", [])
    assert "NOTINGRAPH" in meta.get("omics_unmapped", [])
