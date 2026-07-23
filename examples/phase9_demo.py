"""Phase 9 live smoke demo — network SVG, plots, dashboard session."""

from __future__ import annotations

import os
import sys

# Windows consoles: prefer UTF-8 if available
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ["VOIDSIGNAL_HEADLESS"] = "1"

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
    render_network_svg,
    synergy_heatmap_figure,
    trajectory_comparison_figure,
)
from voidsignal.hpc_runner import aggregate_ensemble
from voidsignal.visualization.plots import ensemble_band_figure


def main() -> None:
    print(f"VOIDSIGNAL {__version__} — Phase 9 visualization smoke demo")
    print("=" * 60)

    net, ids = build_demo_mapk()
    cfg = SimulationConfig(t_end=15.0, dt=0.25, record_every=4)
    traj = DualEngineSimulator(net).run_ode(cfg)

    view = build_network_view(
        net,
        values=traj.final_concentrations(),
        ranks={ids["MEK"]: 0.95, ids["ERK"]: 0.8, ids["RAF"]: 0.6},
    )
    svg = render_network_svg(view)
    print(f"[network] nodes={len(view.nodes)} edges={len(view.edges)} "
          f"loops={len(view.feedback_loops)} svg_bytes={len(svg)}")

    fig = trajectory_comparison_figure({"baseline": traj}, [ids["ERK"], ids["MEK"]])
    print("[trajectory ASCII]")
    print(fig.to_ascii(width=56, height=12))

    curve = DoseResponseCurve(
        doses=[0.01, 0.1, 1.0, 10.0],
        responses=[0.95, 0.8, 0.45, 0.1],
        readout_id="ERK",
        mode="inhibition",
        baseline=1.0,
        ic50=0.9,
        hill_estimate=1.2,
    )
    dr = dose_response_figure(curve)
    print(f"[dose-response] annotations={dr.annotations}")

    heat = synergy_heatmap_figure(
        [[0.0, 0.15, 0.3], [0.1, 0.4, 0.55], [0.2, 0.5, 0.7]],
        doses_a=[0.5, 1.0, 2.0],
        doses_b=[0.5, 1.0, 2.0],
        title="Bliss excess heatmap",
    )
    print("[synergy ASCII]")
    print(heat.to_ascii())

    members = []
    for scale in (0.85, 1.0, 1.15, 0.95):
        members.append(
            {
                "times": list(traj.times),
                "concentrations": [
                    {k: v * scale for k, v in row.items()} for row in traj.concentrations
                ],
            }
        )
    ens = aggregate_ensemble(members)
    band = ensemble_band_figure(ens, [ids["ERK"]], entity_names={ids["ERK"]: "ERK"})
    print(f"[ensemble] series={len(band.series)} svg_bytes={len(band.to_svg())}")

    print("-" * 60)
    print("DashboardSession (cancer + MEK inhibitor)…")
    result = DashboardSession().run(
        DashboardControls(
            dose_c0=2.0,
            t_start=3.0,
            t_end=12.0,
            t_sim=18.0,
            dt=0.5,
            cancer=True,
            drug_target="MEK",
        )
    )
    erk = result.treated.final_concentrations().get(result.ids["ERK"], float("nan"))
    print(
        f"  HSI={result.hsi.hsi:.4f} collapse={result.hsi.collapse_flag} "
        f"tox={len(result.tox_events)} treated_ERK={erk:.4f}"
    )
    recs = result.ai_panel.get("recommendations") or []
    print(f"  AI recommendations={len(recs)} ranks={len(result.ai_panel.get('ranks') or {})}")
    if recs:
        top = recs[0]
        print(f"  top target: {top.get('name')} score={top.get('score'):.4f}")
        print(f"  summary: {(top.get('summary') or '')[:160]}")
    print("=" * 60)
    print("Phase 9 demo OK — launch UI with: streamlit run app.py")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
