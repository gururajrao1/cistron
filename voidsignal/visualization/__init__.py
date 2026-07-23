"""
VOIDSIGNAL visualization package — network graphs, trajectory plots, dashboard helpers.
"""

from voidsignal.visualization.network_view import (
    NetworkViewConfig,
    NetworkViewModel,
    build_network_view,
    render_network_html,
    render_network_svg,
    try_plotly_network,
)
from voidsignal.visualization.plots import (
    FigureSpec,
    PlotSeries,
    dose_response_figure,
    ensemble_band_figure,
    hsi_gauge_figure,
    is_headless,
    pk_clearance_figure,
    synergy_heatmap_figure,
    trajectory_comparison_figure,
)
from voidsignal.visualization.session import (
    DashboardControls,
    DashboardResult,
    DashboardSession,
    build_demo_mapk,
    write_demo_vcf,
)

__all__ = [
    "DashboardControls",
    "DashboardResult",
    "DashboardSession",
    "FigureSpec",
    "NetworkViewConfig",
    "NetworkViewModel",
    "PlotSeries",
    "build_demo_mapk",
    "build_network_view",
    "dose_response_figure",
    "ensemble_band_figure",
    "hsi_gauge_figure",
    "is_headless",
    "pk_clearance_figure",
    "render_network_html",
    "render_network_svg",
    "synergy_heatmap_figure",
    "trajectory_comparison_figure",
    "try_plotly_network",
    "write_demo_vcf",
]
