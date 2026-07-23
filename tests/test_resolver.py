"""Tests for dynamic condition resolver + search-and-simulate API."""

from __future__ import annotations

import time

import pytest

from voidsignal.data.resolver import (
    list_condition_suggestions,
    match_condition_profile,
    resolve_condition_network,
)

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from voidsignal.api.app import create_app


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(create_app()) as c:
        yield c


def test_match_profiles() -> None:
    assert match_condition_profile("Hypoxia-induced angiogenesis").id == "hypoxia"
    assert match_condition_profile("Alzheimer's amyloid stress").id == "alzheimers"
    assert match_condition_profile("Triple-negative breast cancer EGFR survival").id == "tnbc_egfr"
    assert match_condition_profile("DNA Damage p53").id == "dna_damage"


def test_resolve_hypoxia_fast() -> None:
    t0 = time.perf_counter()
    resolved = resolve_condition_network("Hypoxia", use_omnipath=False)
    elapsed = (time.perf_counter() - t0) * 1000.0
    assert elapsed < 500.0
    assert "HIF1A" in resolved.graph.nodes
    assert "VEGFA" in resolved.graph.nodes
    assert resolved.source_node in resolved.graph.nodes
    assert resolved.default_clamps.get("O2") == 0.0


def test_resolve_alzheimers_local() -> None:
    resolved = resolve_condition_network("Alzheimer's Neuroinflammation", use_omnipath=False)
    assert resolved.profile_id == "alzheimers"
    assert "NFKB1" in resolved.graph.nodes or "TNF" in resolved.graph.nodes
    assert resolved.graph.edges
    tnf = resolved.graph.nodes.get("TNF")
    if tnf is not None:
        assert tnf.tau_min >= 1.0


def test_suggestions() -> None:
    tips = list_condition_suggestions()
    assert any("Hypoxia" in t["label"] for t in tips)


def test_search_and_simulate_api(client: TestClient) -> None:
    r = client.post(
        "/api/v1/search-and-simulate",
        json={
            "condition_query": "Hypoxia-induced angiogenesis",
            "custom_knockouts": [],
            "custom_clamps": {},
            "use_omnipath": False,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["profile_id"] == "hypoxia"
    assert len(body["scrubber_payload"]["time_steps"]) == 61
    assert "HIF1A" in body["scrubber_payload"]["nodes"]
    assert body["prioritization"]["master_regulators"]
    assert body["causal_brief"]["brief"]
    assert body["resolved_graph"]["edges"]
    assert body["elapsed_ms"] < 2000.0
    assert any("multi-source" in s.lower() or "Hill-cube" in s for s in body["stages"])


def test_search_alzheimers_with_knockout(client: TestClient) -> None:
    r = client.post(
        "/api/v1/search-and-simulate",
        json={
            "condition_query": "Alzheimer's Neuroinflammation",
            "custom_knockouts": ["TNF"],
            "custom_clamps": {"ROS": 1.0},
            "use_omnipath": False,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scrubber_payload"]["nodes"]["TNF"][-1] == 0.0
    assert "ROS" in body["default_clamps"]


def test_drug_perturbations_alias(client: TestClient) -> None:
    r = client.post(
        "/api/v1/search-and-simulate",
        json={
            "condition_query": "Hypoxia",
            "use_omnipath": False,
            "drug_perturbations": [{"target": "HIF1A", "c_drug": 10.0, "ki": 1.0}],
        },
    )
    assert r.status_code == 200, r.text
    assert "HIF1A" in r.json()["scrubber_payload"]["nodes"]


def test_match_glioblastoma() -> None:
    assert match_condition_profile("Glioblastoma EGFR resistance").id == "glioblastoma"