"""Tests for Causal BioReasoner path extraction and discovery briefs."""

from __future__ import annotations

import pytest

from voidsignal.ai.prioritizer import prioritize
from voidsignal.data.omnipath import hypoxia_network_preset
from voidsignal.engine.solver import HillCubeConfig, HillCubeEngine
from voidsignal.reasoner.bioreasoner import (
    DISCOVERY_BRIEF_RULES,
    attention_to_distance,
    build_causal_context,
    extract_causal_paths,
    extract_causal_paths_timed,
    generate_discovery_brief_prompt,
    synthesize_deterministic_brief,
)
from voidsignal.serialization.scrubber import scrub_simulation


@pytest.fixture
def hypoxia_o2_zero():
    graph = hypoxia_network_preset()
    eng = HillCubeEngine(graph, config=HillCubeConfig(t_end=60.0, dense_output_points=81))
    eng.clamp("O2", 0.0)
    payload = scrub_simulation(eng, t_end=60.0, simulation_id="bio_hypoxia_o2_0")
    prio = prioritize(graph, payload)
    return graph, payload, prio


def test_attention_distance_mapping() -> None:
    assert attention_to_distance(1.0) == pytest.approx(attention_to_distance(1.0))
    assert attention_to_distance(1.0) < attention_to_distance(0.1)
    assert attention_to_distance(0.0) > attention_to_distance(0.5)


def test_dijkstra_extracts_hypoxia_cascade(hypoxia_o2_zero) -> None:
    graph, payload, prio = hypoxia_o2_zero
    paths, elapsed = extract_causal_paths_timed(
        graph, prio, "O2", "VEGFA", k=3
    )
    assert elapsed < 0.002, f"Dijkstra exceeded 2ms budget: {elapsed*1000:.3f} ms"
    assert paths, "expected at least one O2→VEGFA cascade"
    primary = paths[0]
    # Primary hypoxia conduit (graph polarity: O2→EGLN1⊣HIF1A→VEGFA)
    assert primary == ["O2", "EGLN1", "HIF1A", "VEGFA"]
    assert all(len(p) == len(set(p)) for p in paths)  # loopless


def test_path_deltas_and_mechanisms_match_simulation(hypoxia_o2_zero) -> None:
    graph, payload, prio = hypoxia_o2_zero
    ctx = build_causal_context(
        graph, payload, source_node="O2", target_node="VEGFA", k=3, prioritization=prio
    )
    assert ctx.simulation_id == "bio_hypoxia_o2_0"
    assert ctx.extracted_paths
    primary = ctx.extracted_paths[0]
    assert primary.nodes == ["O2", "EGLN1", "HIF1A", "VEGFA"]
    assert primary.mechanisms == [
        "enzymatic",
        "enzymatic",
        "transcriptional",
    ]
    assert primary.signs == [1, -1, 1]

    for node in primary.nodes:
        vec = prio.node_vectors[node]
        assert primary.state_deltas[node] == pytest.approx(vec.delta_y)
        # Δy must match scrubber trajectory endpoints
        traj = payload.nodes[node]
        assert vec.delta_y == pytest.approx(traj[-1] - traj[0])
        assert primary.latencies_min[node] == pytest.approx(graph.nodes[node].tau_min)

    assert "O2" in ctx.perturbed_nodes
    assert ctx.top_master_regulator  # non-empty under hypoxia


def test_discovery_brief_prompt_is_grounded(hypoxia_o2_zero) -> None:
    graph, payload, prio = hypoxia_o2_zero
    ctx = build_causal_context(
        graph, payload, source_node="O2", target_node="VEGFA", prioritization=prio
    )
    prompt = generate_discovery_brief_prompt(ctx)
    assert DISCOVERY_BRIEF_RULES in prompt
    assert "Do not infer unlisted biological relationships" in prompt
    assert "O2 -> EGLN1 -> HIF1A -> VEGFA" in prompt
    assert "enzymatic" in prompt
    assert "transcriptional" in prompt
    # Deterministic offline brief stays inside payload facts
    brief = synthesize_deterministic_brief(ctx)
    assert "O2" in brief and "VEGFA" in brief
    assert ctx.simulation_id in brief
    primary_nodes = ctx.extracted_paths[0].nodes
    for n in primary_nodes:
        assert n in brief
    assert primary_nodes == ["O2", "EGLN1", "HIF1A", "VEGFA"]


def test_extract_causal_paths_api(hypoxia_o2_zero) -> None:
    graph, _, prio = hypoxia_o2_zero
    paths = extract_causal_paths(graph, prio, "O2", "GLUT1", k=2)
    assert paths[0] == ["O2", "EGLN1", "HIF1A", "GLUT1"]
