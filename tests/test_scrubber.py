"""Tests for uniform keyframe scrubber serialization."""

from __future__ import annotations

import json

import numpy as np
import pytest

from cistron.data.omnipath import hypoxia_network_preset
from cistron.engine.solver import HillCubeConfig, HillCubeEngine, SimulationResult
from cistron.models.serialization import ScrubberPayload
from cistron.serialization.scrubber import (
    compute_edge_flux,
    edge_flux_key,
    sample_uniform_keyframes,
    scrub_simulation,
)


def test_edge_flux_hill_cube() -> None:
    assert compute_edge_flux(0.0, sign=1) == pytest.approx(0.0)
    assert compute_edge_flux(0.5, sign=1) == pytest.approx(0.5)
    assert compute_edge_flux(0.5, sign=-1) == pytest.approx(0.5)
    assert compute_edge_flux(0.0, sign=-1) == pytest.approx(1.0)
    assert edge_flux_key("EGLN1", "HIF1A") == "EGLN1->HIF1A"


def test_scrubber_61_keyframes_hypoxia() -> None:
    graph = hypoxia_network_preset()
    eng = HillCubeEngine(graph, config=HillCubeConfig(t_end=60.0, dense_output_points=81))
    eng.clamp("O2", 1.0)
    payload = scrub_simulation(eng, t_end=60.0, n_intervals=60, simulation_id="hypoxia_hi_o2")

    assert isinstance(payload, ScrubberPayload)
    assert payload.simulation_id == "hypoxia_hi_o2"
    assert payload.n_keyframes() == 61
    assert payload.time_steps[0] == pytest.approx(0.0)
    assert payload.time_steps[-1] == pytest.approx(60.0)
    assert payload.time_steps == pytest.approx(list(np.linspace(0.0, 60.0, 61)))

    for sym, traj in payload.nodes.items():
        assert len(traj) == 61
        assert all(0.0 <= v <= 1.0 for v in traj)

    assert "O2->EGLN1" in payload.edges
    assert "EGLN1->HIF1A" in payload.edges
    assert "HIF1A->VEGFA" in payload.edges
    for key, flux in payload.edges.items():
        assert "->" in key
        assert len(flux) == 61
        assert all(0.0 <= v <= 1.0 for v in flux)

    # Inhibitory edge uses 1 - hill(source)
    egln = payload.nodes["EGLN1"]
    inhib = payload.edges["EGLN1->HIF1A"]
    for y, f in zip(egln, inhib):
        assert f == pytest.approx(compute_edge_flux(y, sign=-1), abs=1e-9)


def test_sample_from_simulation_result_alias() -> None:
    graph = hypoxia_network_preset()
    eng = HillCubeEngine(graph, config=HillCubeConfig(t_end=60.0))
    eng.clamp("O2", 0.0)
    raw = eng.simulate()
    assert isinstance(raw, SimulationResult)
    payload = sample_uniform_keyframes(raw, graph, metadata={"omics": False})
    assert payload.metadata["omics"] is False
    assert payload.metadata["graph_name"] == "hypoxia_preset"
    # JSON round-trip for frontend
    blob = json.dumps(payload.to_json_dict())
    restored = ScrubberPayload.model_validate_json(blob)
    assert restored.n_keyframes() == 61
    assert restored.nodes["HIF1A"][-1] == pytest.approx(payload.nodes["HIF1A"][-1])
