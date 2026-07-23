"""Tests for AI target prioritization and graph attention."""

from __future__ import annotations

import numpy as np
import pytest

from cistron.ai.prioritizer import (
    ATTENTION_EPS,
    compute_attention_matrix,
    node_feature_array,
    prioritize,
    rank_combination_targets,
    resolve_output_nodes,
)
from cistron.data.omnipath import hypoxia_network_preset
from cistron.engine.solver import HillCubeConfig, HillCubeEngine
from cistron.serialization.scrubber import scrub_simulation


@pytest.fixture
def hypoxia_payload():
    graph = hypoxia_network_preset()
    eng = HillCubeEngine(graph, config=HillCubeConfig(t_end=60.0, dense_output_points=81))
    eng.clamp("O2", 0.0)  # hypoxia → HIF pathway on
    payload = scrub_simulation(eng, t_end=60.0, simulation_id="prio_hypoxia")
    return graph, payload


def test_5d_node_vectors(hypoxia_payload) -> None:
    graph, payload = hypoxia_payload
    result = prioritize(graph, payload)

    assert "HIF1A" in result.node_vectors
    h = result.node_vectors["HIF1A"]
    arr = node_feature_array(h)
    assert arr.shape == (5,)
    assert arr[0] == pytest.approx(h.y_init)
    assert arr[1] == pytest.approx(h.y_final)
    assert arr[2] == pytest.approx(h.delta_y)
    assert arr[3] == pytest.approx(h.capacity)
    assert arr[4] in (0.0, 1.0)
    assert h.delta_y == pytest.approx(h.y_final - h.y_init)


def test_attention_sums_to_one(hypoxia_payload) -> None:
    graph, payload = hypoxia_payload
    alphas = compute_attention_matrix(graph, payload)

    # Incoming to HIF1A: EGLN1->HIF1A, MTOR->HIF1A
    hif_in = [k for k in alphas if k.endswith("->HIF1A")]
    assert "EGLN1->HIF1A" in hif_in
    assert "MTOR->HIF1A" in hif_in
    s = sum(alphas[k] for k in hif_in)
    assert s == pytest.approx(1.0, abs=1e-6)

    # Every target with ≥1 inbound edge has Σα = 1
    targets = {e.target for e in graph.edges}
    for tgt in targets:
        keys = [k for k in alphas if k.endswith(f"->{tgt}")]
        assert sum(alphas[k] for k in keys) == pytest.approx(1.0, abs=1e-6)


def test_master_regulator_ranking(hypoxia_payload) -> None:
    graph, payload = hypoxia_payload
    result = prioritize(graph, payload)
    assert result.master_regulators
    names = [n for n, _ in result.master_regulators]
    scores = [s for _, s in result.master_regulators]
    assert scores == sorted(scores, reverse=True)
    # HIF1A drives VEGFA/GLUT1/EGLN1 — should rank among top drivers under hypoxia
    assert "HIF1A" in names[:3]
    assert all(s >= 0.0 for s in scores)


def test_rank_combination_targets(hypoxia_payload) -> None:
    graph, payload = hypoxia_payload
    outs = resolve_output_nodes(graph)
    assert "VEGFA" in outs and "GLUT1" in outs

    ranked = rank_combination_targets(
        graph,
        payload,
        candidates=["HIF1A", "MTOR", "EGLN1"],
        output_nodes=outs,
        top_k=5,
    )
    assert ranked
    assert ranked[0].output_sum <= ranked[-1].output_sum
    # Dual HIF1A + MTOR should suppress outputs strongly vs baseline
    pairs = {(c.target_a, c.target_b): c for c in ranked}
    assert ("HIF1A", "MTOR") in pairs or ("MTOR", "HIF1A") in pairs
    best = ranked[0]
    assert best.output_sum <= best.baseline_output_sum + ATTENTION_EPS
    assert best.synergy_score == pytest.approx(
        (
            (best.single_a_output_sum * best.single_b_output_sum) / best.baseline_output_sum
            if best.baseline_output_sum > ATTENTION_EPS
            else min(best.single_a_output_sum, best.single_b_output_sum)
        )
        - best.output_sum,
        abs=1e-6,
    )


def test_knockout_flag_in_vector() -> None:
    graph = hypoxia_network_preset()
    eng = HillCubeEngine(graph, config=HillCubeConfig(t_end=60.0))
    eng.clamp("O2", 1.0)
    eng.knockout(["HIF1A"])
    payload = scrub_simulation(eng, t_end=60.0)
    result = prioritize(graph, payload)
    assert result.node_vectors["HIF1A"].is_knocked_out is True
    assert result.node_vectors["HIF1A"].capacity == pytest.approx(0.0)
    assert node_feature_array(result.node_vectors["HIF1A"])[4] == pytest.approx(1.0)
