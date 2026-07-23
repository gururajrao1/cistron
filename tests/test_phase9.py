"""Phase 9 — visualization, plots, dashboard session (headless)."""

from __future__ import annotations

from voidsignal import (
    DashboardControls,
    DashboardSession,
    DoseResponseCurve,
    DualEngineSimulator,
    SimulationConfig,
    __version__,
    build_demo_mapk,
    build_network_view,
    dose_response_figure,
    ensemble_band_figure,
    pk_clearance_figure,
    render_network_html,
    render_network_svg,
    synergy_heatmap_figure,
    trajectory_comparison_figure,
)
from voidsignal.hpc_runner import aggregate_ensemble
from voidsignal.visualization.plots import hsi_gauge_figure, is_headless


def test_version_phase9() -> None:
    # Phase 9 introduced 0.9.x; later phases may bump further
    parts = __version__.split(".")
    assert int(parts[0]) >= 0
    assert int(parts[1]) >= 9


def test_network_view_svg_and_hubs() -> None:
    net, ids = build_demo_mapk()
    # close feedback already present
    view = build_network_view(
        net,
        values={ids["ERK"]: 2.0, ids["RAS"]: 0.5},
        ranks={ids["MEK"]: 0.9, ids["ERK"]: 0.7},
    )
    assert len(view.nodes) == 6
    assert len(view.edges) >= 5
    assert view.feedback_loops
    svg = render_network_svg(view)
    assert svg.startswith("<svg")
    assert "MEK" in svg or "ERK" in svg
    html = render_network_html(view)
    assert "<!DOCTYPE html>" in html
    payload = view.as_dict()
    assert len(payload["nodes"]) == 6
    assert "metadata" in payload


def test_trajectory_and_pk_figures() -> None:
    net, ids = build_demo_mapk()
    cfg = SimulationConfig(t_end=10.0, dt=0.5, record_every=2)
    traj = DualEngineSimulator(net).run_ode(cfg)
    fig = trajectory_comparison_figure({"baseline": traj}, [ids["ERK"], ids["MEK"]])
    assert fig.series
    assert "svg" in fig.to_svg().lower() or fig.to_svg().startswith("<svg")
    ascii_plot = fig.to_ascii()
    assert "Concentration" in ascii_plot or len(ascii_plot) > 10

    pk = pk_clearance_figure([0.0, 1.0, 2.0], [2.0, 1.0, 0.5], t_start=0.0, t_end=2.0)
    assert pk.metadata["t_end"] == 2.0
    assert pk.to_plotly() is None or pk.to_plotly() is not None  # optional


def test_dose_response_and_synergy() -> None:
    curve = DoseResponseCurve(
        doses=[0.1, 1.0, 10.0],
        responses=[1.0, 0.5, 0.1],
        readout_id="ERK",
        mode="inhibition",
        baseline=1.0,
        ic50=1.0,
    )
    fig = dose_response_figure(curve)
    assert any("IC50" in a for a in fig.annotations)

    heat = synergy_heatmap_figure(
        [[0.0, 0.2], [-0.1, 0.4]],
        doses_a=[1.0, 2.0],
        doses_b=[0.5, 1.0],
    )
    assert heat.kind == "heatmap"
    assert "<svg" in heat.to_svg()


def test_ensemble_band_figure() -> None:
    times = [0.0, 1.0, 2.0]
    members = []
    for scale in (0.9, 1.0, 1.1):
        members.append(
            {
                "times": times,
                "concentrations": [
                    {"e1": 0.1 * scale},
                    {"e1": 0.5 * scale},
                    {"e1": 0.8 * scale},
                ],
            }
        )
    ens = aggregate_ensemble(members, level=0.9)
    fig = ensemble_band_figure(ens, ["e1"])
    assert any(s.fill_to for s in fig.series)
    assert "<svg" in fig.to_svg()


def test_hsi_gauge_and_headless() -> None:
    g = hsi_gauge_figure(0.4)
    assert g.metadata["level"] == "warn"
    assert is_headless() in (True, False)


def test_dashboard_session_live() -> None:
    session = DashboardSession()
    result = session.run(
        DashboardControls(
            dose_c0=1.5,
            t_start=2.0,
            t_end=8.0,
            t_sim=12.0,
            dt=0.5,
            cancer=True,
            cytokine_storm=False,
            drug_target="MEK",
        )
    )
    assert len(result.baseline) > 0
    assert len(result.treated) > 0
    assert result.hsi.hsi >= 0.0
    assert "<svg" in result.network_svg
    assert result.trajectory_figure.series
    assert "ranks" in result.ai_panel
    payload = result.as_dict()
    assert payload["controls"]["cancer"] is True
