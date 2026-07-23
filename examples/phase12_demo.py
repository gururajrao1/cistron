"""Phase 12 live smoke demo — multi-omics → MassActionRHS bridge."""

from __future__ import annotations

import os
import sys

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ["VOIDSIGNAL_HEADLESS"] = "1"

from voidsignal import (
    DualEngineSimulator,
    InteractionType,
    KineticParameters,
    Protein,
    SignalingNetwork,
    SimulationConfig,
    __version__,
)
from voidsignal.omics import MultiOmicsBridge, make_demo_multiomics_profile
from voidsignal.patient_profile import PatientSignalingNetwork


def build_mapk() -> tuple[SignalingNetwork, dict[str, str]]:
    net = SignalingNetwork(name="omics_demo")
    ids: dict[str, str] = {}
    for name, conc in (
        ("EGF", 1.0),
        ("EGFR", 0.5),
        ("RAS", 0.4),
        ("RAF", 0.35),
        ("MEK", 0.3),
        ("ERK", 0.25),
    ):
        p = Protein(
            name=name,
            concentration=conc,
            kinetics=KineticParameters(
                production_rate=0.05,
                degradation_rate=0.08,
                vmax=1.0,
                km=1.0,
            ),
            is_enzyme=name in {"EGFR", "RAF", "MEK", "ERK"},
        )
        if name == "EGF":
            p.set_boolean(True)
        net.add_node(p)
        ids[name] = p.entity_id
    net.connect(ids["EGF"], ids["EGFR"], InteractionType.ACTIVATION, rate_constant=1.2)
    net.connect(ids["EGFR"], ids["RAS"], InteractionType.ACTIVATION, rate_constant=1.0)
    net.connect(ids["RAS"], ids["RAF"], InteractionType.ACTIVATION, rate_constant=1.0)
    net.connect(ids["RAF"], ids["MEK"], InteractionType.PHOSPHORYLATION, rate_constant=1.0)
    net.connect(ids["MEK"], ids["ERK"], InteractionType.PHOSPHORYLATION, rate_constant=1.0)
    return net, ids


def main() -> int:
    print(f"VOIDSIGNAL {__version__} - Phase 12 multi-omics smoke demo")
    print("=" * 60)

    net, ids = build_mapk()
    patient = PatientSignalingNetwork(patient_id="OMICS_DEMO_P", network=net)
    baseline_erk_vmax = net.registry.get(ids["ERK"]).kinetics.vmax
    baseline_egfr_prod = net.registry.get(ids["EGFR"]).kinetics.production_rate

    bridge = MultiOmicsBridge()
    result = bridge.apply(patient, make_demo_multiomics_profile())
    print(f"[layers] {result.layers_applied}")

    if result.transcription_scales:
        egfr_tx = result.transcription_scales.get("EGFR")
        if egfr_tx:
            print(
                f"[epi] EGFR transcription scale={egfr_tx.scale:.3f} "
                f"(meth={egfr_tx.methylation_factor:.3f})"
            )
    if "MEK" in result.splicing_effects:
        sp = result.splicing_effects["MEK"]
        print(f"[splice] MEK kcat_scale={sp.kcat_scale:.3f} psi_eff={sp.effective_psi:.3f}")
    if "ERK" in result.ptm_states:
        ptm = result.ptm_states["ERK"]
        print(
            f"[ptm] ERK active={ptm.active_fraction:.3f} "
            f"kcat_scale={ptm.kcat_scale:.3f}"
        )
    if result.fba is not None:
        print(
            f"[fba] obj={result.fba.objective_value:.4f} "
            f"residual={result.fba.residual_norm:.3e} "
            f"ATP_demand={result.fba.flux('atp_maintenance'):.3f}"
        )

    egfr = result.network.registry.get(ids["EGFR"])
    erk = result.network.registry.get(ids["ERK"])
    print(
        f"[kinetics] EGFR production {baseline_egfr_prod:.4f} -> {egfr.kinetics.production_rate:.4f}"
    )
    print(f"[kinetics] ERK vmax {baseline_erk_vmax:.4f} -> {erk.kinetics.vmax:.4f}")

    eng = DualEngineSimulator(result.network)
    traj = eng.run_ode(SimulationConfig(t_end=15.0, dt=0.5))
    final_erk = traj.final_concentrations()[ids["ERK"]]
    print(f"[ode] steps={len(traj)} final ERK={final_erk:.4f}")
    print("=" * 60)
    print("Phase 12 demo OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
