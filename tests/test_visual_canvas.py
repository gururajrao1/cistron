"""Visual pathway canvas exporter — ODE trajectory → animated frame states."""

from __future__ import annotations

import math

import pytest

from cistron import (
    DualEngineSimulator,
    InteractionType,
    KineticParameters,
    Protein,
    SignalingNetwork,
    SimulationConfig,
    __version__,
)
from cistron.ui.visual_translator import (
    VISUAL_LEGEND,
    EdgeVisualState,
    NodeVisualState,
    VisualPathwayTranslator,
    VisualTranslatorConfig,
    build_tme_visual,
    classify_node_activity,
    flux_to_pulse_speed,
    flux_to_thickness,
    make_demo_visual_timeline,
)


def _mapk() -> tuple[SignalingNetwork, dict[str, str]]:
    net = SignalingNetwork(name="visual_mapk")
    ids: dict[str, str] = {}
    for name, conc in (
        ("EGF", 1.0),
        ("EGFR", 0.6),
        ("RAS", 0.45),
        ("RAF", 0.4),
        ("MEK", 0.35),
        ("ERK", 0.3),
    ):
        p = Protein(
            name=name,
            concentration=conc,
            kinetics=KineticParameters(
                production_rate=0.05,
                degradation_rate=0.08,
                vmax=1.2 if name in {"EGFR", "MEK", "ERK"} else 1.0,
                km=1.0,
            ),
            is_enzyme=name != "EGF",
        )
        if name == "EGF":
            p.set_boolean(True)
        if name == "EGFR":
            p.metadata["mutated"] = True
        net.add_node(p)
        ids[name] = p.entity_id
    net.connect(ids["EGF"], ids["EGFR"], InteractionType.ACTIVATION, rate_constant=1.2)
    net.connect(ids["EGFR"], ids["RAS"], InteractionType.ACTIVATION, rate_constant=1.1)
    net.connect(ids["RAS"], ids["RAF"], InteractionType.ACTIVATION, rate_constant=1.0)
    net.connect(ids["RAF"], ids["MEK"], InteractionType.PHOSPHORYLATION, rate_constant=1.0)
    net.connect(ids["MEK"], ids["ERK"], InteractionType.PHOSPHORYLATION, rate_constant=1.15)
    return net, ids


def test_version_visual_canvas() -> None:
    major, minor, *_ = __version__.split(".")
    assert int(major) >= 0 and int(minor) >= 16


def test_classify_node_states() -> None:
    assert classify_node_activity(0.9) is NodeVisualState.OVERACTIVE
    assert classify_node_activity(0.4) is NodeVisualState.HOMEOSTATIC
    assert classify_node_activity(0.1) is NodeVisualState.QUIESCENT
    assert classify_node_activity(0.2, inhibited=True) is NodeVisualState.INHIBITED


def test_flux_animation_params() -> None:
    assert flux_to_thickness(0.0) < flux_to_thickness(5.0)
    assert flux_to_pulse_speed(0.0) == 0.0
    assert flux_to_pulse_speed(3.0) > 0.5
    assert flux_to_pulse_speed(3.0, blocked=True) == 0.0


def test_frame_exports_colors_and_inspect() -> None:
    net, ids = _mapk()
    conc = {eid: net.registry.get(eid).concentration for eid in ids.values()}
    frame = VisualPathwayTranslator().frame_from_concentrations(net, conc, t=0.0)
    assert len(frame.nodes) == 6
    assert len(frame.edges) == 5
    egfr = frame.node_map()[ids["EGFR"]]
    assert egfr.color.startswith("#")
    assert "concentration" in egfr.inspect
    assert egfr.mutated is True
    # Raw numeric inspect present but primary state is visual enum
    assert egfr.state in NodeVisualState


def test_drug_block_zeros_pulse_and_dashes_edge() -> None:
    net, ids = _mapk()
    conc = {eid: net.registry.get(eid).concentration for eid in ids.values()}
    cfg = VisualTranslatorConfig(drug_blocked_targets=(ids["MEK"],), mutated_ids=(ids["EGFR"],))
    frame = VisualPathwayTranslator(cfg).frame_from_concentrations(net, conc)
    mek_out = [e for e in frame.edges if e.source_id == ids["MEK"]]
    assert mek_out
    for e in mek_out:
        assert e.state is EdgeVisualState.BLOCKED
        assert e.pulse_speed == 0.0
        assert e.blocked is True
        assert e.dash == "6,5"
        assert e.inspect["flux"] == 0.0


def test_knockout_fades_node() -> None:
    net, ids = _mapk()
    conc = {eid: net.registry.get(eid).concentration for eid in ids.values()}
    cfg = VisualTranslatorConfig(knocked_out_ids=(ids["EGFR"],), drug_blocked_targets=(ids["EGFR"],))
    frame = VisualPathwayTranslator(cfg).frame_from_concentrations(net, conc)
    egfr = frame.node_map()[ids["EGFR"]]
    assert egfr.state in (NodeVisualState.INHIBITED, NodeVisualState.QUIESCENT)
    assert egfr.activity <= 0.05


def test_timeline_from_ode_trajectory() -> None:
    net, ids = _mapk()
    eng = DualEngineSimulator(net)
    traj = eng.run_ode(SimulationConfig(t_end=10.0, dt=0.5))
    timeline = make_demo_visual_timeline(net, traj, mutated=("EGFR",), drug_target="MEK")
    assert len(timeline) >= 2
    assert timeline.t_end >= timeline.t_start
    mid = timeline.at_time(0.5 * (timeline.t_start + timeline.t_end))
    assert mid.nodes and mid.edges
    # velocity vectors present on edges
    for e in mid.edges:
        payload = e.as_dict()
        assert "velocity" in payload
        assert "magnitude" in payload["velocity"]
        assert math.isfinite(payload["flux"])
    assert "overactive" in timeline.legend
    assert VISUAL_LEGEND["homeostatic"]["label"]


def test_tme_cytokine_heatmap() -> None:
    scene = build_tme_visual(t=5.0, grid=10)
    assert scene.cells
    assert any(c.kind == "tumor" for c in scene.cells)
    assert any(c.kind == "ctl" for c in scene.cells)
    assert len(scene.fields) >= 1
    f = scene.fields[0]
    assert len(f.values) == 10 and len(f.values[0]) == 10
    assert max(max(row) for row in f.values) > 0.1
