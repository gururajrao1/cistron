"""Phase 11 — docking parser, scoring, pharmacology kinetic bridge."""

from __future__ import annotations

import math

import pytest

from voidsignal import (
    DrugAgent,
    DualEngineSimulator,
    InteractionType,
    Protein,
    SignalingNetwork,
    SimulationConfig,
    __version__,
)
from voidsignal.docking import (
    BindingScorer,
    DockedDrugSpec,
    DockingKineticsBridge,
    delta_g_to_ki,
    ki_to_delta_g,
    load_structure,
    make_demo_receptor_ligand,
    parse_pdb,
    parse_pdbqt,
    parse_smiles,
    scales_from_docking,
)


SAMPLE_PDB = """\
ATOM      1  N   POC A   1       3.200   0.000   0.200  1.00 20.00           N  
ATOM      2  O   POC A   1       1.500   2.598   0.000  1.00 20.00           O  
ATOM      3  C   POC A   1      -1.600   2.771  -0.200  1.00 20.00           C  
ATOM      4  C   POC A   1      -3.200   0.000   0.000  1.00 20.00           C  
ATOM      5  O   POC A   1      -1.550  -2.685   0.200  1.00 20.00           O  
ATOM      6  N   POC A   1       1.650  -2.858  -0.200  1.00 20.00           N  
END
"""

SAMPLE_PDBQT = """\
REMARK  VOIDSIGNAL demo ligand
ROOT
ATOM      1  C1  LIG L   1       0.000   0.000   0.000  0.00  0.00    +0.100 A
ATOM      2  N1  LIG L   1       1.300   0.000   0.000  0.00  0.00    -0.400 N
ATOM      3  O1  LIG L   1      -1.200   0.400   0.000  0.00  0.00    -0.500 OA
ATOM      4  C2  LIG L   1       0.000   1.400   0.300  0.00  0.00    +0.000 A
ENDROOT
TORSDOF 3
"""


def test_version_phase11() -> None:
    major, minor, *_ = __version__.split(".")
    assert int(major) >= 0 and int(minor) >= 12


def test_parse_pdb_and_box() -> None:
    mol = parse_pdb(SAMPLE_PDB, name="pocket")
    assert mol.n_atoms == 6
    assert mol.box is not None
    assert mol.box.volume() > 0
    assert any(a.element == "N" for a in mol.atoms)


def test_parse_pdbqt_charges_and_torsdof() -> None:
    lig = parse_pdbqt(SAMPLE_PDBQT, name="inh")
    assert lig.n_atoms == 4
    assert lig.metadata.get("torsdof") == 3
    charges = [a.charge for a in lig.atoms]
    assert min(charges) < 0  # has OA/N negative
    assert lig.n_rotatable >= 1


def test_parse_smiles_layout() -> None:
    mol = parse_smiles("CC(=O)Oc1ccccc1C(=O)O", name="aspirin_like")
    assert mol.n_atoms >= 5
    assert mol.smiles is not None
    assert mol.box is not None
    # rotatable single bonds present
    assert mol.n_rotatable >= 1


def test_delta_g_ki_roundtrip() -> None:
    for dg in (-10.0, -6.0, -2.0, 0.0, 1.5):
        ki = delta_g_to_ki(dg)
        back = ki_to_delta_g(ki)
        assert ki > 0
        assert abs(back - dg) < 1e-9 or abs(back - dg) / max(abs(dg), 1e-9) < 1e-6


def test_scoring_stability_and_contacts() -> None:
    receptor, ligand = make_demo_receptor_ligand()
    scorer = BindingScorer()
    s1 = scorer.score(receptor, ligand)
    s2 = scorer.score(receptor, ligand)
    assert s1.delta_g == pytest.approx(s2.delta_g)
    assert s1.n_contacts > 0
    assert s1.ki == pytest.approx(delta_g_to_ki(s1.delta_g))
    assert math.isfinite(s1.ki_uM)


def test_far_pose_worse_than_bound() -> None:
    from voidsignal.docking.scoring import local_pose_search, translate_molecule

    receptor, ligand = make_demo_receptor_ligand()
    scorer = BindingScorer()
    bound = local_pose_search(receptor, ligand, scorer=scorer, step=0.5, grid=1)
    far = scorer.score(receptor, translate_molecule(ligand, 25.0, 0.0, 0.0))
    assert bound.n_contacts > far.n_contacts
    assert bound.delta_g < far.delta_g


def test_scales_and_bridge_updates_kinetics() -> None:
    net = SignalingNetwork(name="dock_test")
    mek = Protein(name="MEK", concentration=0.5)
    erk = Protein(name="ERK", concentration=0.2)
    net.add_node(mek)
    net.add_node(erk)
    net.connect(mek.entity_id, erk.entity_id, InteractionType.PHOSPHORYLATION, rate_constant=1.0)
    mek.metadata["structure_disruption"] = 0.2
    v_before = mek.kinetics.vmax
    rate_before = list(net.out_edges(mek.entity_id))[0].rate_constant

    receptor, ligand = make_demo_receptor_ligand()
    bridge = DockingKineticsBridge(pose_search=False)
    result = bridge.bridge(
        net,
        receptor,
        ligand,
        DockedDrugSpec(target_id=mek.entity_id, ligand_name="demo", dose=2.0, t_end=30.0),
        apply_network_scales=True,
    )
    assert result.applied_to_network
    assert result.agent.ki > 0
    assert isinstance(result.agent, DrugAgent)
    assert mek.kinetics.vmax <= v_before + 1e-12
    assert list(net.out_edges(mek.entity_id))[0].rate_constant <= rate_before + 1e-12
    assert result.scales.kcat_scale <= 1.0
    assert "docking_ki" in mek.metadata


def test_docked_agent_runs_in_ode() -> None:
    net = SignalingNetwork(name="dock_ode")
    ids = {}
    for name, c in (("A", 1.0), ("B", 0.2), ("C", 0.0)):
        p = Protein(name=name, concentration=c)
        if name == "A":
            p.set_boolean(True)
        net.add_node(p)
        ids[name] = p.entity_id
    net.connect(ids["A"], ids["B"], InteractionType.ACTIVATION, rate_constant=1.0)
    net.connect(ids["B"], ids["C"], InteractionType.ACTIVATION, rate_constant=1.0)

    receptor, ligand = make_demo_receptor_ligand()
    bridge = DockingKineticsBridge(pose_search=True)
    result = bridge.bridge(
        net,
        receptor,
        ligand,
        DockedDrugSpec(
            target_id=ids["B"],
            ligand_name="inh",
            dose=3.0,
            t_start=2.0,
            t_end=12.0,
            plateau=3.0,
        ),
    )
    eng = DualEngineSimulator(net)
    eng.add_hook(result.agent.apply)
    traj = eng.run_ode(SimulationConfig(t_end=16.0, dt=0.5, record_every=2))
    assert len(traj) > 0
    assert result.agent.ki == pytest.approx(result.score.ki)


def test_load_structure_dispatch() -> None:
    mol = load_structure(SAMPLE_PDBQT, fmt="pdbqt")
    assert mol.source_format == "pdbqt"
    smi = load_structure("CCO", fmt="smiles")
    assert smi.n_atoms >= 2
