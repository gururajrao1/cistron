"""Tests for multi-source knowledge resolver."""

from __future__ import annotations

import time

import pytest

from cistron.data.multisource import (
    fuse_edges,
    list_available_sources,
    normalize_sources,
    resolve_multisource_network,
)
from cistron.models.graph import ActivityFlowEdge, MechanismKind

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from cistron.api.app import create_app


def _edge(src: str, tgt: str, sign: int = 1, *tags: str) -> ActivityFlowEdge:
    return ActivityFlowEdge(
        source=src,
        target=tgt,
        sign=1 if sign >= 0 else -1,  # type: ignore[arg-type]
        is_stimulation=sign >= 0,
        is_inhibition=sign < 0,
        consensus_modification="test",
        mechanism=MechanismKind.ENZYMATIC,
        sources=list(tags),
        datasets=list(tags),
        evidence_score=0.8,
    )


def test_normalize_sources() -> None:
    assert "omnipath" in normalize_sources(["OmniPath", "STRING"])
    assert normalize_sources([])[0] == "local"


def test_fuse_consensus() -> None:
    batches = {
        "local": [_edge("EGF", "EGFR", 1, "local")],
        "string": [_edge("EGF", "EGFR", 1, "string")],
        "kegg": [_edge("EGF", "EGFR", -1, "kegg")],  # conflict — lower weight
    }
    fused = fuse_edges(batches)
    match = [e for e in fused if e.source == "EGF" and e.target == "EGFR"]
    assert match
    assert "local" in match[0].sources
    assert match[0].evidence_score is not None


def test_multisource_local_fast() -> None:
    t0 = time.perf_counter()
    resolved = resolve_multisource_network(
        "Hypoxia",
        selected_sources=["local", "uniprot"],
        use_omnipath=False,
    )
    elapsed = (time.perf_counter() - t0) * 1000.0
    assert elapsed < 800.0
    assert "HIF1A" in resolved.graph.nodes or "VEGFA" in resolved.graph.nodes
    assert resolved.graph.edges
    assert resolved.provenance.get("selected_sources")


def test_multisource_glioblastoma_offline_bundle() -> None:
    resolved = resolve_multisource_network(
        "Glioblastoma EGFR resistance",
        selected_sources=["local", "kegg", "reactome", "string", "biogrid", "uniprot"],
        use_omnipath=False,
    )
    assert resolved.profile_id == "glioblastoma"
    assert len(resolved.graph.edges) >= 5
    # Provenance badges on fused edges
    assert any(e.sources for e in resolved.graph.edges)


def test_sources_endpoint() -> None:
    tips = list_available_sources()
    ids = {t["id"] for t in tips}
    assert {"omnipath", "signor", "kegg", "string", "biogrid", "uniprot"} <= ids


def test_search_with_selected_sources() -> None:
    with TestClient(create_app()) as client:
        r = client.post(
            "/api/v1/search-and-simulate",
            json={
                "condition_query": "Hypoxia-induced angiogenesis",
                "selected_sources": ["local", "uniprot"],
                "use_omnipath": False,
                "custom_clamps": {"O2": 0.0},
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["elapsed_ms"] < 1500.0
        assert body["scientist_reasoning"]["elapsed_ms"] < 20.0
        assert body["xai_attributions"]["node_attributions"]
        assert body["metadata"]["provenance"]["selected_sources"]
        src = client.get("/api/v1/sources")
        assert src.status_code == 200
        assert len(src.json()) >= 6
