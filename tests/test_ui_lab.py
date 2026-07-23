"""Tests for Virtual Cellular Laboratory Streamlit helpers (no browser)."""

from __future__ import annotations

import pytest

from voidsignal.lifecycle import VoidSignalPipeline, VoidSignalPipelineConfig
from voidsignal.ui.app import build_network_figure, build_trajectory_figure, lerp_at_time


@pytest.fixture(scope="module")
def lab_result():
    pytest.importorskip("plotly")
    cfg = VoidSignalPipelineConfig(
        preset="hypoxia",
        clamps={"O2": 0.0},
        source_node="O2",
        target_node="VEGFA",
        simulation_id="lab_test",
    )
    pipe = VoidSignalPipeline(cfg)
    return pipe.run(), pipe.ingest()


def test_lerp_does_not_need_rerun(lab_result) -> None:
    result, _graph = lab_result
    payload = result.scrubber
    y0, f0 = lerp_at_time(payload, 0.0)
    y60, f60 = lerp_at_time(payload, 60.0)
    y30, _ = lerp_at_time(payload, 30.0)

    assert y0["HIF1A"] == pytest.approx(payload.nodes["HIF1A"][0])
    assert y60["HIF1A"] == pytest.approx(payload.nodes["HIF1A"][-1])
    # Integer keyframe should match the stored sample exactly
    assert 30.0 in payload.time_steps
    idx = payload.time_steps.index(30.0)
    assert y30["HIF1A"] == pytest.approx(payload.nodes["HIF1A"][idx])
    # Half-step lerp sits between neighboring keyframes
    y30_5, _ = lerp_at_time(payload, 30.5)
    a, b = payload.nodes["HIF1A"][idx], payload.nodes["HIF1A"][idx + 1]
    assert y30_5["HIF1A"] == pytest.approx(0.5 * (a + b))
    assert "EGLN1->HIF1A" in f0 and "EGLN1->HIF1A" in f60


def test_figures_build(lab_result) -> None:
    result, graph = lab_result
    node_y, edge_f = lerp_at_time(result.scrubber, 12.0)
    fig_n = build_network_figure(graph, node_y, edge_f, t=12.0, path_nodes=["O2", "EGLN1", "HIF1A", "VEGFA"])
    fig_t = build_trajectory_figure(
        result.scrubber, focus=("O2", "HIF1A", "VEGFA"), playhead=12.0
    )
    assert len(fig_n.data) >= 1
    assert len(fig_t.data) >= 1
