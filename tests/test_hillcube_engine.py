"""Hill-cube ODE engine tests — hypoxia preset + knockout stability."""

from __future__ import annotations

import numpy as np
import pytest

from voidsignal.data.omnipath import hypoxia_network_preset
from voidsignal.engine.solver import (
    DrugDose,
    FootprintPriors,
    HillCubeConfig,
    HillCubeEngine,
    combine_inputs,
    hill_activation,
    hill_inhibition,
    logic_and,
    logic_or,
    simulate_graph,
)


def test_hill_cube_math() -> None:
    assert hill_activation(0.0) == 0.0
    assert hill_activation(0.5) == pytest.approx(0.5, abs=1e-9)
    assert hill_activation(10.0) > 0.99
    assert hill_inhibition(0.0) == pytest.approx(1.0)
    assert logic_or(0.5, 0.5) == pytest.approx(0.75)
    assert logic_and(0.5, 0.4) == pytest.approx(0.2)
    assert combine_inputs([0.8], [0.5]) == pytest.approx(0.8 * 0.5)


def test_hypoxia_high_o2_suppresses_hif_and_vegfa() -> None:
    graph = hypoxia_network_preset()
    eng = HillCubeEngine(graph, config=HillCubeConfig(t_end=60.0, method="RK45"))
    eng.clamp("O2", 1.0)
    # Constitutive MTOR still present but EGLN1 should dominate HIF off
    result = eng.simulate()
    assert result.success
    fin = result.final()
    assert fin["O2"] == pytest.approx(1.0)
    assert fin["EGLN1"] > 0.5
    assert fin["HIF1A"] < 0.35
    assert fin["VEGFA"] < 0.4


def test_hypoxia_anoxia_accumulates_hif1a() -> None:
    graph = hypoxia_network_preset()
    eng = HillCubeEngine(graph, config=HillCubeConfig(t_end=60.0, method="RK45"))
    eng.clamp("O2", 0.0)
    result = eng.simulate()
    assert result.success
    fin = result.final()
    assert fin["O2"] == pytest.approx(0.0)
    # EGLN1 may partially recover via HIF→EGLN1 feedback; O2 drive is off
    assert fin["HIF1A"] > 0.45
    assert fin["VEGFA"] > 0.35
    high = simulate_graph(graph, clamp={"O2": 1.0}, t_end=60.0)
    assert fin["HIF1A"] > high.final()["HIF1A"]
    assert fin["VEGFA"] > high.final()["VEGFA"]


def test_knockout_extinguishes_downstream_stably() -> None:
    graph = hypoxia_network_preset()
    # Transcriptional τ=120 min — integrate long enough for VEGFA washout
    eng = HillCubeEngine(graph, config=HillCubeConfig(t_end=400.0))
    eng.clamp("O2", 0.0)
    eng.knockout(["HIF1A"])
    result = eng.simulate()
    assert result.success
    fin = result.final()
    assert fin["HIF1A"] == pytest.approx(0.0, abs=1e-9)
    assert fin["VEGFA"] < 0.15
    assert fin["GLUT1"] < 0.15
    assert np.all(np.isfinite(result.states["VEGFA"]))
    assert np.all(result.states["HIF1A"] >= 0.0)
    assert np.all(result.states["HIF1A"] <= 1.0)


def test_drug_pkpd_scales_capacity() -> None:
    graph = hypoxia_network_preset()
    eng = HillCubeEngine(graph)
    eng.clamp("O2", 0.0)
    eng.apply_drug(DrugDose(target="HIF1A", c_drug=10.0, ki=1.0))
    # Occupancy = 10/11 → scale ≈ 0.091
    assert eng.weights["HIF1A"] == pytest.approx(
        graph.nodes["HIF1A"].activity_weight * (1.0 - 10.0 / 11.0),
        rel=1e-6,
    )
    result = eng.simulate(t_end=40.0)
    assert result.success
    assert result.final()["HIF1A"] < 0.25


def test_viper_footprint_initializes_master_regulator() -> None:
    graph = hypoxia_network_preset()
    eng = HillCubeEngine(graph)
    eng.clamp("O2", 0.0)
    eng.apply_footprints(
        FootprintPriors(
            expression={"VEGFA": 0.9, "GLUT1": 0.8, "EGLN1": 0.2},
            regulons={"HIF1A": {"VEGFA": 1.0, "GLUT1": 1.0, "EGLN1": 0.5}},
            fold_changes={"VEGFA": 1.0},  # 2^1 = 2 → clipped to 1.0 capacity
        )
    )
    assert "HIF1A" in eng.y0_override
    assert 0.0 <= eng.y0_override["HIF1A"] <= 1.0
    assert eng.weights["VEGFA"] == pytest.approx(1.0)  # clipped
    result = eng.simulate(t_end=30.0)
    assert result.success
    assert result.metadata["footprint"]["viper_scores"]


def test_lsoda_method_runs() -> None:
    graph = hypoxia_network_preset()
    result = simulate_graph(
        graph,
        clamp={"O2": 0.5},
        config=HillCubeConfig(method="LSODA", t_end=20.0, dense_output_points=41),
    )
    assert result.success
    assert len(result.times) == 41
