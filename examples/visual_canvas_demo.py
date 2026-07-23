"""Visual canvas smoke — ODE trajectory to animated pathway frames."""

from __future__ import annotations

import os
import sys

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from voidsignal import (
    DualEngineSimulator,
    InteractionType,
    KineticParameters,
    Protein,
    SignalingNetwork,
    SimulationConfig,
    __version__,
)
from voidsignal.ui.visual_translator import (
    EdgeVisualState,
    VisualPathwayTranslator,
    VisualTranslatorConfig,
    build_tme_visual,
    make_demo_visual_timeline,
)


def main() -> int:
    print(f"VOIDSIGNAL {__version__} - visual pathway canvas smoke")
    print("=" * 60)

    net = SignalingNetwork(name="viz_demo")
    ids = {}
    for name, c in (("EGF", 1.0), ("EGFR", 0.5), ("MEK", 0.3), ("ERK", 0.25)):
        p = Protein(
            name=name,
            concentration=c,
            kinetics=KineticParameters(vmax=1.2, production_rate=0.05, degradation_rate=0.08),
        )
        if name == "EGF":
            p.set_boolean(True)
        net.add_node(p)
        ids[name] = p.entity_id
    net.connect(ids["EGF"], ids["EGFR"], InteractionType.ACTIVATION, rate_constant=1.2)
    net.connect(ids["EGFR"], ids["MEK"], InteractionType.ACTIVATION, rate_constant=1.0)
    net.connect(ids["MEK"], ids["ERK"], InteractionType.PHOSPHORYLATION, rate_constant=1.1)

    traj = DualEngineSimulator(net).run_ode(SimulationConfig(t_end=12.0, dt=0.5))
    timeline = make_demo_visual_timeline(net, traj, mutated=("EGFR",), drug_target="MEK")
    print(f"[timeline] frames={len(timeline)} t=[{timeline.t_start:.1f}, {timeline.t_end:.1f}]")

    fr = timeline.frames[-1]
    blocked = sum(1 for e in fr.edges if e.state is EdgeVisualState.BLOCKED)
    flowing = sum(1 for e in fr.edges if e.pulse_speed > 0)
    print(f"[frame] nodes={len(fr.nodes)} edges={len(fr.edges)} blocked={blocked} pulsing={flowing}")
    for n in fr.nodes:
        print(f"  node {n.label}: state={n.state.value} activity={n.activity:.2f}")
    for e in fr.edges:
        print(
            f"  edge {e.kind}: flux={e.flux:.3f} thick={e.thickness:.1f} "
            f"speed={e.pulse_speed:.2f} blocked={e.blocked}"
        )

    tme = build_tme_visual(t=4.0)
    print(f"[tme] cells={len(tme.cells)} cytokine_fields={len(tme.fields)}")
    print("=" * 60)
    print("Visual canvas demo OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
