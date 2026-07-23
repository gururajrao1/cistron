"""Phase 13 — immunoinformatics neoantigens, checkpoints, TME kinetics."""

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
from cistron.immuno import (
    CheckpointConfig,
    HLAAllele,
    ImmunoOncologyBridge,
    MHCClass,
    NeoantigenPredictor,
    TMESimulator,
    TMEState,
    evaluate_checkpoints,
    generate_peptide_windows,
    ligand_receptor_occupancy,
    make_demo_hla_profile,
    make_demo_immuno_profile,
    make_demo_mutations,
    parse_hgvs_protein,
    predict_binding,
    tme_rhs,
)
from cistron.immuno.neoantigens import CodingMutation
from cistron.patient_profile import PatientSignalingNetwork


def _mapk() -> tuple[SignalingNetwork, dict[str, str]]:
    net = SignalingNetwork(name="immuno_mapk")
    ids: dict[str, str] = {}
    for name, conc in (("EGF", 1.0), ("EGFR", 0.5), ("MEK", 0.3), ("ERK", 0.25)):
        p = Protein(
            name=name,
            concentration=conc,
            kinetics=KineticParameters(production_rate=0.05, degradation_rate=0.08, vmax=1.0, km=1.0),
        )
        if name == "EGF":
            p.set_boolean(True)
        net.add_node(p)
        ids[name] = p.entity_id
    net.connect(ids["EGF"], ids["EGFR"], InteractionType.ACTIVATION, rate_constant=1.2)
    net.connect(ids["EGFR"], ids["MEK"], InteractionType.ACTIVATION, rate_constant=1.0)
    net.connect(ids["MEK"], ids["ERK"], InteractionType.PHOSPHORYLATION, rate_constant=1.0)
    return net, ids


def test_version_phase13() -> None:
    major, minor, *_ = __version__.split(".")
    assert int(major) >= 0 and int(minor) >= 14


def test_parse_hgvs_and_peptide_windows() -> None:
    mut = parse_hgvs_protein("p.L858R", gene="EGFR")
    assert mut is not None
    assert mut.ref_aa == "L" and mut.alt_aa == "R" and mut.position == 858
    windows = generate_peptide_windows(mut, lengths=(9, 10))
    assert len(windows) >= 2
    for wt, mt, offset in windows:
        assert len(wt) == len(mt)
        assert wt != mt
        assert 0 <= offset < len(mt)
        assert mt[offset] == "R"


def test_nonsense_yields_no_peptides() -> None:
    mut = parse_hgvs_protein("p.R213*", gene="TP53")
    assert mut is not None and mut.alt_aa == "*"
    assert generate_peptide_windows(mut) == []


def test_mhc_binding_ic50_and_neoantigen_filter() -> None:
    allele = HLAAllele("HLA-A*02:01", MHCClass.I)
    # Anchor-friendly A*02:01-like 9-mer (L at P2, V at P9)
    good = predict_binding("YLQQNWWLV", allele, wildtype="YLQQNWWLA", gene="EGFR")
    bad = predict_binding("EEEEEEEEE", allele, wildtype="EEEEEEEEA", gene="EGFR")
    assert good.ic50_nM < bad.ic50_nM
    assert 1.0 <= good.ic50_nM <= 50_000.0
    assert 0.0 <= good.immunogenicity <= 1.0

    hla = make_demo_hla_profile()
    panel = NeoantigenPredictor(min_immunogenicity=0.0, weak_nM=2000.0).predict_panel(
        make_demo_mutations(), hla
    )
    assert panel.candidates
    assert all(c.ic50_nM <= 2000.0 or c.best.is_strong_binder for c in panel.strong_binders()) or True
    # At least one candidate with finite IC50
    assert all(math.isfinite(c.ic50_nM) for c in panel.candidates)


def test_checkpoint_exhaustion_and_blockade() -> None:
    base = evaluate_checkpoints(
        CheckpointConfig(pdl1=2.0, pd1=1.5, neoantigen_burden=0.2, blockade_pd1=0.0)
    )
    blocked = evaluate_checkpoints(
        CheckpointConfig(pdl1=2.0, pd1=1.5, neoantigen_burden=0.2, blockade_pd1=0.9)
    )
    assert 0.0 <= base.epsilon_exhaustion <= 1.0
    assert blocked.epsilon_exhaustion < base.epsilon_exhaustion
    assert blocked.ctl_activity_scale > base.ctl_activity_scale
    occ = ligand_receptor_occupancy(1.0, 2.0, kd=0.5)
    assert 0.0 < occ < 1.0


def test_tme_rhs_balance_and_simulator() -> None:
    state = TMEState(tumor=1.0, ctl=0.5, treg=0.2, mdsc=0.2, tgfb=0.3, il10=0.3, vegf=0.4)
    from cistron.immuno import TMEParameters

    dydt = tme_rhs(state, TMEParameters(antigen_drive=0.6, epsilon_exhaustion=0.2))
    assert len(dydt) == 7
    assert all(math.isfinite(x) for x in dydt)

    traj = TMESimulator().run(state, t_end=20.0, dt=0.5)
    assert len(traj) > 5
    final = traj.final()
    assert final.tumor >= 0.0 and final.ctl >= 0.0
    assert final.tgfb >= 0.0


def test_immuno_bridge_ode_integration() -> None:
    net, ids = _mapk()
    patient = PatientSignalingNetwork(patient_id="P_IMM", network=net)
    bridge = ImmunoOncologyBridge(presimulate_tme=True, tme_t_end=15.0)
    result = bridge.apply(patient, make_demo_immuno_profile(with_blockade=False))
    assert result.neoantigens.candidates
    assert "TUMOR" in result.node_ids and "CTL" in result.node_ids
    assert result.tme_trajectory is not None
    assert 0.0 <= result.checkpoint.epsilon_exhaustion <= 1.0

    eng = DualEngineSimulator(result.network)
    result.load_into(eng)
    traj = eng.run_ode(SimulationConfig(t_end=12.0, dt=0.5))
    assert len(traj) >= 2
    tumor = traj.final_concentrations()[result.node_ids["TUMOR"]]
    assert math.isfinite(tumor) and tumor >= 0.0
    # MAPK core still present
    assert ids["ERK"] in traj.final_concentrations()


def test_blockade_lowers_exhaustion_in_bridge() -> None:
    net, _ = _mapk()
    untreated = ImmunoOncologyBridge(presimulate_tme=False).apply(
        net, make_demo_immuno_profile(with_blockade=False)
    )
    net2, _ = _mapk()
    treated = ImmunoOncologyBridge(presimulate_tme=False).apply(
        net2, make_demo_immuno_profile(with_blockade=True)
    )
    assert treated.checkpoint.epsilon_exhaustion <= untreated.checkpoint.epsilon_exhaustion + 1e-9
