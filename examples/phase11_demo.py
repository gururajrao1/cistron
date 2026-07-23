"""Phase 11 live smoke demo — docking ΔG / Ki → DrugAgent ODE bridge."""

from __future__ import annotations

import os
import sys

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ["CISTRON_HEADLESS"] = "1"

from cistron import (
    DualEngineSimulator,
    InteractionType,
    Protein,
    SignalingNetwork,
    SimulationConfig,
    __version__,
)
from cistron.docking import (
    BindingScorer,
    DockedDrugSpec,
    DockingKineticsBridge,
    delta_g_to_ki,
    make_demo_receptor_ligand,
    parse_smiles,
)


def main() -> int:
    print(f"CISTRON {__version__} — Phase 11 docking smoke demo")
    print("=" * 60)

    receptor, ligand = make_demo_receptor_ligand()
    from cistron.docking import local_pose_search

    scorer = BindingScorer()
    score = local_pose_search(receptor, ligand, scorer=scorer, step=0.5, grid=2)
    print(
        f"[score] dG={score.delta_g:.3f} kcal/mol  Ki={score.ki:.3e} M "
        f"({score.ki_uM:.3g} uM)  contacts={score.n_contacts} hbonds={score.n_hbonds}"
    )
    print(f"        terms={score.terms.as_dict()}")
    assert abs(score.ki - delta_g_to_ki(score.delta_g)) < 1e-12 * max(1.0, score.ki)

    smi = parse_smiles("CCN(CC)CCCC(C)Nc1ccnc2cc(Cl)ccc12", name="chloroquine_like")
    print(f"[smiles] atoms={smi.n_atoms} rotatable={smi.n_rotatable} box={smi.ensure_box().as_dict()}")

    net = SignalingNetwork(name="dock_demo")
    ids = {}
    for name, c in (("EGF", 1.0), ("EGFR", 0.4), ("MEK", 0.3), ("ERK", 0.2)):
        p = Protein(name=name, concentration=c)
        if name == "EGF":
            p.set_boolean(True)
        net.add_node(p)
        ids[name] = p.entity_id
    net.connect(ids["EGF"], ids["EGFR"], InteractionType.ACTIVATION, rate_constant=1.2)
    net.connect(ids["EGFR"], ids["MEK"], InteractionType.ACTIVATION, rate_constant=1.0)
    net.connect(ids["MEK"], ids["ERK"], InteractionType.PHOSPHORYLATION, rate_constant=1.0)

    bridge = DockingKineticsBridge(pose_search=True)
    result = bridge.bridge(
        net,
        receptor,
        ligand,
        DockedDrugSpec(
            target_id=ids["MEK"],
            ligand_name="demo_inhibitor",
            dose=2.5,
            t_start=3.0,
            t_end=25.0,
            plateau=2.5,
        ),
        disruption=0.15,
    )
    print(
        f"[bridge] agent={result.agent.name} Ki={result.agent.ki:.3e} "
        f"kcat_scale={result.scales.kcat_scale:.3f} km_scale={result.scales.km_scale:.3f}"
    )

    eng = DualEngineSimulator(net)
    eng.add_hook(result.agent.apply)
    traj = eng.run_ode(SimulationConfig(t_end=30.0, dt=0.5, record_every=2))
    erk = traj.final_concentrations()[ids["ERK"]]
    print(f"[ode] steps={len(traj)} final ERK={erk:.4f}")
    print("=" * 60)
    print("Phase 11 demo OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
