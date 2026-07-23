"""FastAPI gateway tests (TestClient) — routes must stay under 50 ms warm."""

from __future__ import annotations

import time

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from voidsignal.api.app import create_app

LATENCY_BUDGET_MS = 100.0


@pytest.fixture(scope="module")
def client() -> TestClient:
    app = create_app()
    with TestClient(app) as c:
        # Warm import / scipy / preset caches so latency asserts measure work
        c.get("/health")
        c.get("/presets")
        c.post(
            "/simulate",
            json={"preset": "hypoxia", "clamps": {"O2": 0.0}, "simulation_id": "warmup"},
        )
        yield c


def _assert_fast(elapsed_ms: float, route: str) -> None:
    assert elapsed_ms < LATENCY_BUDGET_MS, (
        f"{route} took {elapsed_ms:.2f} ms (budget {LATENCY_BUDGET_MS} ms)"
    )


def test_health(client: TestClient) -> None:
    t0 = time.perf_counter()
    r = client.get("/health")
    elapsed = (time.perf_counter() - t0) * 1000.0
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "timestamp" in body
    assert "database_handles" in body
    assert "presets_loaded" in body["database_handles"]
    _assert_fast(elapsed, "GET /health")


def test_list_presets(client: TestClient) -> None:
    t0 = time.perf_counter()
    r = client.get("/presets")
    elapsed = (time.perf_counter() - t0) * 1000.0
    assert r.status_code == 200
    presets = r.json()
    ids = {p["id"] for p in presets}
    assert "hypoxia" in ids
    assert "mapk" in ids
    hypo = next(p for p in presets if p["id"] == "hypoxia")
    assert hypo["n_nodes"] >= 5
    assert "HIF1A" in hypo["nodes"]
    _assert_fast(elapsed, "GET /presets")


def test_get_preset_detail(client: TestClient) -> None:
    t0 = time.perf_counter()
    r = client.get("/presets/hypoxia")
    elapsed = (time.perf_counter() - t0) * 1000.0
    assert r.status_code == 200
    detail = r.json()
    assert detail["name"] == "hypoxia_preset"
    assert "EGLN1" in detail["nodes"]
    assert any(e["source"] == "O2" and e["target"] == "EGLN1" for e in detail["edges"])
    _assert_fast(elapsed, "GET /presets/hypoxia")


def test_unknown_preset_404(client: TestClient) -> None:
    r = client.get("/presets/not-a-real-preset")
    assert r.status_code == 404


def test_simulate_hypoxia_scrubber(client: TestClient) -> None:
    t0 = time.perf_counter()
    r = client.post(
        "/simulate",
        json={
            "preset": "hypoxia",
            "clamps": {"O2": 0.0},
            "knockouts": [],
            "drugs": [],
            "simulation_id": "api_hypoxia_o2_0",
            "dense_output_points": 61,
        },
    )
    elapsed = (time.perf_counter() - t0) * 1000.0
    assert r.status_code == 200, r.text
    body = r.json()
    payload = body["payload"]
    assert payload["simulation_id"] == "api_hypoxia_o2_0"
    assert len(payload["time_steps"]) == 61
    assert payload["time_steps"][0] == 0.0
    assert payload["time_steps"][-1] == 60.0
    assert "HIF1A" in payload["nodes"]
    assert len(payload["nodes"]["HIF1A"]) == 61
    assert "EGLN1->HIF1A" in payload["edges"]
    assert body["elapsed_ms"] < LATENCY_BUDGET_MS
    _assert_fast(elapsed, "POST /simulate")


def test_simulate_with_knockout_and_drug(client: TestClient) -> None:
    t0 = time.perf_counter()
    r = client.post(
        "/simulate",
        json={
            "preset": "hypoxia",
            "clamps": {"O2": 0.0},
            "knockouts": ["MTOR"],
            "drugs": [{"target": "HIF1A", "c_drug": 10.0, "ki": 1.0}],
            "simulation_id": "api_combo",
        },
    )
    elapsed = (time.perf_counter() - t0) * 1000.0
    assert r.status_code == 200, r.text
    payload = r.json()["payload"]
    assert payload["nodes"]["MTOR"][-1] == 0.0
    assert "HIF1A" in payload["metadata"]["weights"]
    assert payload["metadata"]["weights"]["HIF1A"] < 1.0
    _assert_fast(elapsed, "POST /simulate (ko+drug)")


def test_prioritize(client: TestClient) -> None:
    sim = client.post(
        "/simulate",
        json={"preset": "hypoxia", "clamps": {"O2": 0.0}, "simulation_id": "prio_in"},
    ).json()["payload"]

    t0 = time.perf_counter()
    r = client.post("/prioritize", json={"preset": "hypoxia", "payload": sim})
    elapsed = (time.perf_counter() - t0) * 1000.0
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    assert "HIF1A" in result["node_vectors"]
    hv = result["node_vectors"]["HIF1A"]
    assert "y_init" in hv and "delta_y" in hv and "capacity" in hv
    assert "EGLN1->HIF1A" in result["attention_matrix"]
    assert result["master_regulators"]
    assert result["master_regulators"][0][1] >= result["master_regulators"][-1][1]
    _assert_fast(elapsed, "POST /prioritize")


def test_reason_bioreasoner(client: TestClient) -> None:
    sim = client.post(
        "/simulate",
        json={"preset": "hypoxia", "clamps": {"O2": 0.0}, "simulation_id": "reason_in"},
    ).json()["payload"]

    t0 = time.perf_counter()
    r = client.post(
        "/reason",
        json={
            "preset": "hypoxia",
            "payload": sim,
            "source_node": "O2",
            "target_node": "VEGFA",
            "k": 3,
            "include_brief": True,
            "include_prompt": True,
        },
    )
    elapsed = (time.perf_counter() - t0) * 1000.0
    assert r.status_code == 200, r.text
    body = r.json()
    ctx = body["context"]
    assert ctx["extracted_paths"]
    assert ctx["extracted_paths"][0]["nodes"] == ["O2", "EGLN1", "HIF1A", "VEGFA"]
    assert "O2" in ctx["perturbed_nodes"]
    assert body["brief"] and "VEGFA" in body["brief"]
    assert body["prompt"] and "Do not infer unlisted biological relationships" in body["prompt"]
    _assert_fast(elapsed, "POST /reason")


def test_reason_bad_source(client: TestClient) -> None:
    sim = client.post(
        "/simulate",
        json={"preset": "hypoxia", "clamps": {"O2": 1.0}},
    ).json()["payload"]
    r = client.post(
        "/reason",
        json={
            "preset": "hypoxia",
            "payload": sim,
            "source_node": "NOT_A_GENE",
            "target_node": "VEGFA",
        },
    )
    assert r.status_code == 400


def test_api_v1_aliases(client: TestClient) -> None:
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/presets/hypoxia").status_code == 200
    sim = client.post(
        "/api/v1/simulate",
        json={"preset": "hypoxia", "clamps": {"O2": 0.0}, "simulation_id": "v1"},
    )
    assert sim.status_code == 200
    payload = sim.json()["payload"]
    brief = client.post(
        "/api/v1/reasoner/brief",
        json={
            "preset": "hypoxia",
            "payload": payload,
            "source_node": "O2",
            "target_node": "VEGFA",
        },
    )
    assert brief.status_code == 200
    assert brief.json()["brief"]
