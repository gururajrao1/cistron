"""Phase 2 — stiff LSODA scrubber + server 2-compartment translocation."""

from __future__ import annotations

import numpy as np
import pytest

from cistron.data.omnipath import hypoxia_network_preset
from cistron.engine.compartments import (
    TranslocationParams,
    integrate_hif1a_translocation,
)
from cistron.engine.solver import HillCubeConfig, HillCubeEngine
from cistron.serialization.scrubber import scrub_simulation


def test_lsoda_nonnegative_dense_output() -> None:
    graph = hypoxia_network_preset()
    eng = HillCubeEngine(
        graph,
        config=HillCubeConfig(t_end=60.0, dense_output_points=100, method="LSODA"),
    )
    eng.clamp("O2", 0.15)
    raw = eng.simulate()
    assert raw.metadata.get("method") == "LSODA"
    assert raw.metadata.get("nonnegative") is True
    assert len(raw.times) == 100
    for series in raw.states.values():
        assert np.all(np.asarray(series) >= -1e-12)


def test_hif1a_translocation_hypoxia_raises_nucleus() -> None:
    t = np.linspace(0.0, 60.0, 61)
    o2_low = np.full_like(t, 0.05)
    o2_hi = np.full_like(t, 0.95)
    low = integrate_hif1a_translocation(t, o2_low, params=TranslocationParams())
    hi = integrate_hif1a_translocation(t, o2_hi, params=TranslocationParams())
    assert low["nuc"][-1] > hi["nuc"][-1]
    assert all(0.0 <= v <= 1.0 for v in low["cyto"] + low["nuc"])
    assert all(0.0 <= v <= 1.0 for v in hi["cyto"] + hi["nuc"])


def test_scrubber_payload_has_trajectories_and_compartments() -> None:
    graph = hypoxia_network_preset()
    eng = HillCubeEngine(graph, config=HillCubeConfig(t_end=60.0, dense_output_points=100))
    eng.clamp("O2", 0.2)
    payload = scrub_simulation(eng, t_end=60.0, n_intervals=60, simulation_id="phase2")
    assert payload.time_steps[0] == pytest.approx(0.0)
    assert payload.time_steps[-1] == pytest.approx(60.0)
    assert set(payload.trajectories.keys()) == set(payload.nodes.keys())
    assert payload.trajectories["HIF1A"] == payload.nodes["HIF1A"]
    assert "cyto" in payload.compartments and "nuc" in payload.compartments
    assert len(payload.compartments["cyto"]) == len(payload.time_steps)
    assert len(payload.compartments["nuc"]) == len(payload.time_steps)
    assert payload.metadata.get("compartments", {}).get("ok") is True
