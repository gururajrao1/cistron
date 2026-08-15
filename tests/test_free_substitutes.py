"""Free-safe substitutes — literature, Saltelli-lite, in-process jobs."""

from __future__ import annotations

import time

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from cistron.ai.saltelli_lite import saltelli_lite
from cistron.api.app import create_app
from cistron.models.graph import ActivityFlowEdge, CausalActivityGraph, GraphNode


@pytest.fixture(scope="module")
def client() -> TestClient:
    app = create_app()
    with TestClient(app) as c:
        yield c


def _tiny_graph() -> CausalActivityGraph:
    return CausalActivityGraph(
        nodes={
            "A": GraphNode(gene_symbol="A", tau_min=1.0, activity_weight=1.0, initial_concentration=0.6),
            "B": GraphNode(gene_symbol="B", tau_min=1.0, activity_weight=1.0, initial_concentration=0.4),
            "C": GraphNode(gene_symbol="C", tau_min=1.0, activity_weight=1.0, initial_concentration=0.3),
        },
        edges=[
            ActivityFlowEdge(
                source="A",
                target="B",
                sign=1,
                is_stimulation=True,
                is_inhibition=False,
            ),
            ActivityFlowEdge(
                source="B",
                target="C",
                sign=1,
                is_stimulation=True,
                is_inhibition=False,
            ),
        ],
    )


def test_saltelli_lite_unit() -> None:
    out = saltelli_lite(_tiny_graph(), readout="C", n_base=4, t_end=20.0)
    assert out["ok"] is True
    assert out["method"] == "saltelli_lite_numpy"
    assert len(out["factors"]) == len(out["S_i"]) == len(out["S_Ti"])
    assert len(out["factors"]) >= 4
    assert all(0.0 <= s <= 1.5 for s in out["S_i"])


def test_literature_copilot_empty_query(client: TestClient) -> None:
    r = client.get("/api/v1/literature/copilot")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["mode"] == "retrieve"
    assert body["citations"] == []


def test_literature_copilot_shape(client: TestClient) -> None:
    r = client.get(
        "/api/v1/literature/copilot",
        params={"gene": "HIF1A", "disease": "hypoxia", "max_hits": 3},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "retrieve"
    assert "citations" in body and "reactome" in body and "summary" in body
    # Network may be offline in CI — shape must still be stable
    assert isinstance(body["citations"], list)
    assert isinstance(body["reactome"], list)


def test_sensitivity_saltelli_requires_graph(client: TestClient) -> None:
    r = client.post(
        "/api/v1/sensitivity/saltelli",
        json={"graph_id": "missing", "readout": "HIF1A"},
    )
    assert r.status_code == 422


def test_sensitivity_saltelli_on_active_graph(client: TestClient) -> None:
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
        "/api/v1/sensitivity/saltelli",
        json={"graph_id": graph_id, "readout": "VEGFA", "n_base": 4, "t_end": 30},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["factors"]
    assert len(body["S_Ti"]) == len(body["factors"])


def test_jobs_search_and_simulate(client: TestClient) -> None:
    r = client.post(
        "/api/v1/jobs/search-and-simulate",
        json={
            "condition_query": "Hypoxia-induced angiogenesis",
            "use_omnipath": False,
            "selected_sources": ["local"],
        },
    )
    assert r.status_code == 200, r.text
    jid = r.json()["job_id"]
    assert jid
    deadline = time.time() + 30
    body = None
    while time.time() < deadline:
        poll = client.get(f"/api/v1/jobs/{jid}")
        assert poll.status_code == 200
        body = poll.json()
        if body["status"] in {"done", "error"}:
            break
        time.sleep(0.15)
    assert body is not None
    assert body["status"] == "done", body
    assert body.get("result", {}).get("profile_id") == "hypoxia"


def test_jobs_unknown_404(client: TestClient) -> None:
    r = client.get("/api/v1/jobs/does-not-exist")
    assert r.status_code == 404
