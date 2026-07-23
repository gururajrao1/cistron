"""Tests for topological vulnerability & synthetic lethality analysis."""

from __future__ import annotations

import time

import pytest

from cistron.data.resolver import resolve_condition_network
from cistron.engine import HillCubeConfig, HillCubeEngine
from cistron.math.topology import (
    analyze_topology_vulnerabilities,
    betweenness_centrality,
    detect_feedback_loops,
)
from cistron.serialization import scrub_simulation

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from cistron.api.app import create_app


def _hypoxia():
    resolved = resolve_condition_network("Hypoxia", use_omnipath=False)
    eng = HillCubeEngine(
        resolved.graph,
        config=HillCubeConfig(t_end=60.0, dense_output_points=61),
    )
    eng.clamp("O2", 0.0)
    payload = scrub_simulation(eng, t_end=60.0, simulation_id="topo_test")
    return resolved.graph, payload


def test_betweenness_and_loops() -> None:
    graph, _ = _hypoxia()
    nodes = sorted(graph.nodes.keys())
    succ = {n: [] for n in nodes}
    signs = {}
    for e in graph.edges:
        succ.setdefault(e.source, []).append(e.target)
        signs[(e.source, e.target)] = int(e.sign)
    bc = betweenness_centrality(succ, nodes)
    assert all(0.0 <= v <= 1.0 + 1e-6 for v in bc.values())
    loops = detect_feedback_loops(succ, signs, nodes)
    # Hypoxia has HIF1A → EGLN1 feedback
    assert isinstance(loops, list)


def test_analyze_topology_fast() -> None:
    graph, payload = _hypoxia()
    t0 = time.perf_counter()
    topo = analyze_topology_vulnerabilities(graph, payload=payload)
    elapsed = (time.perf_counter() - t0) * 1000.0
    assert elapsed < 2000.0
    assert topo.bottlenecks
    assert topo.bottlenecks[0].node
    assert topo.elapsed_ms < 2000.0


def test_api_includes_topological_analysis() -> None:
    with TestClient(create_app()) as client:
        r = client.post(
            "/api/v1/search-and-simulate",
            json={
                "condition_query": "Hypoxia-induced angiogenesis",
                "selected_sources": ["local"],
                "use_omnipath": False,
                "custom_clamps": {"O2": 0.0},
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        topo = body["topological_analysis"]
        assert topo["bottlenecks"]
        assert "betweenness" in topo["bottlenecks"][0]
        assert "feedback_loops" in topo
        assert "synthetic_lethal_pairs" in topo
        assert body["elapsed_ms"] < 1500.0
        assert body["scientist_reasoning"]["elapsed_ms"] < 20.0
        assert len(body["scrubber_payload"]["time_steps"]) == 61
