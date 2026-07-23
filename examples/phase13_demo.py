"""Phase 13 live smoke demo — neoantigens, checkpoints, TME kinetics."""

from __future__ import annotations

import os
import sys

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ["CISTRON_HEADLESS"] = "1"

from cistron import (
    DualEngineSimulator,
    InteractionType,
    KineticParameters,
    Protein,
    SignalingNetwork,
    SimulationConfig,
    __version__,
)
from cistron.immuno import ImmunoOncologyBridge, make_demo_immuno_profile
from cistron.patient_profile import PatientSignalingNetwork


def build_net() -> tuple[SignalingNetwork, dict[str, str]]:
    net = SignalingNetwork(name="immuno_demo")
    ids: dict[str, str] = {}
    for name, conc in (("EGF", 1.0), ("EGFR", 0.5), ("MEK", 0.3), ("ERK", 0.25)):
        p = Protein(
            name=name,
            concentration=conc,
            kinetics=KineticParameters(production_rate=0.05, degradation_rate=0.08, vmax=1.0),
        )
        if name == "EGF":
            p.set_boolean(True)
        net.add_node(p)
        ids[name] = p.entity_id
    net.connect(ids["EGF"], ids["EGFR"], InteractionType.ACTIVATION, rate_constant=1.2)
    net.connect(ids["EGFR"], ids["MEK"], InteractionType.ACTIVATION, rate_constant=1.0)
    net.connect(ids["MEK"], ids["ERK"], InteractionType.PHOSPHORYLATION, rate_constant=1.0)
    return net, ids


def main() -> int:
    print(f"CISTRON {__version__} - Phase 13 immuno-oncology smoke demo")
    print("=" * 60)

    net, ids = build_net()
    patient = PatientSignalingNetwork(patient_id="IMMUNO_DEMO_P", network=net)
    bridge = ImmunoOncologyBridge(presimulate_tme=True, tme_t_end=25.0)
    result = bridge.apply(patient, make_demo_immuno_profile(with_blockade=True))

    print(f"[neo] candidates={len(result.neoantigens.candidates)} strong={len(result.neoantigens.strong_binders())}")
    for rec in result.neoantigens.top(3):
        print(
            f"      {rec.gene} {rec.mutant_peptide} @ {rec.best.allele} "
            f"IC50={rec.ic50_nM:.1f}nM immuno={rec.immunogenicity:.3f}"
        )
    print(
        f"[ckpt] epsilon={result.checkpoint.epsilon_exhaustion:.3f} "
        f"ctl_scale={result.checkpoint.ctl_activity_scale:.3f} "
        f"apoptosis_scale={result.checkpoint.apoptosis_scale:.3f}"
    )
    if result.tme_trajectory is not None:
        fin = result.tme_trajectory.final()
        print(
            f"[tme] tumor={fin.tumor:.3f} CTL={fin.ctl:.3f} Treg={fin.treg:.3f} "
            f"MDSC={fin.mdsc:.3f} TGFb={fin.tgfb:.3f}"
        )

    eng = DualEngineSimulator(result.network)
    result.load_into(eng)
    traj = eng.run_ode(SimulationConfig(t_end=15.0, dt=0.5))
    tumor = traj.final_concentrations()[result.node_ids["TUMOR"]]
    ctl = traj.final_concentrations()[result.node_ids["CTL"]]
    erk = traj.final_concentrations()[ids["ERK"]]
    print(f"[ode] steps={len(traj)} tumor={tumor:.4f} CTL={ctl:.4f} ERK={erk:.4f}")
    print("=" * 60)
    print("Phase 13 demo OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
