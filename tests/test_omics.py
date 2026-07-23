"""Phase 12 — multi-omics epigenomics, splicing, PTM, FBA + ODE bridge."""

from __future__ import annotations

import math

import pytest

from voidsignal import (
    DualEngineSimulator,
    InteractionType,
    KineticParameters,
    Protein,
    SignalingNetwork,
    SimulationConfig,
    __version__,
)
from voidsignal.omics import (
    EpigenomicTransformer,
    MethylationRecord,
    MultiOmicsBridge,
    MultiOmicsProfile,
    PTMKind,
    PTMSite,
    PTMTransformer,
    SplicingTransformer,
    aggregate_psi,
    aggregate_ptm_state,
    build_core_energy_network,
    make_demo_epigenomic_profile,
    make_demo_metabolomic_profile,
    make_demo_multiomics_profile,
    make_demo_ptm_profile,
    make_demo_splicing_profile,
    methylation_factor,
    michaelis_menten_multiplier,
    parse_psi_matrix,
    solve_fba,
)
from voidsignal.omics.splicing import IsoformRecord
from voidsignal.patient_profile import PatientSignalingNetwork


def _mapk() -> tuple[SignalingNetwork, dict[str, str]]:
    net = SignalingNetwork(name="omics_mapk")
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
                binding_affinity=1.0,
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


def test_version_phase12() -> None:
    major, minor, *_ = __version__.split(".")
    assert int(major) >= 0 and int(minor) >= 13


def test_methylation_represses_transcription() -> None:
    assert methylation_factor(0.0) == pytest.approx(1.0)
    assert methylation_factor(1.0) < 0.2
    assert methylation_factor(0.5) < methylation_factor(0.1)


def test_epigenomics_scales_production() -> None:
    net, ids = _mapk()
    egfr = net.registry.get(ids["EGFR"])
    before = egfr.kinetics.production_rate
    scales = EpigenomicTransformer().apply(net, make_demo_epigenomic_profile())
    assert "EGFR" in scales
    assert scales["EGFR"].scale < 1.0  # hypermethylated
    assert net.registry.get(ids["EGFR"]).kinetics.production_rate < before


def test_psi_aggregate_and_apply() -> None:
    isoforms = [
        IsoformRecord("MEK", "canon", 0.7, catalytic_efficiency=1.0, kinase_domain=True),
        IsoformRecord("MEK", "dKD", 0.3, catalytic_efficiency=0.1, kinase_domain=False),
    ]
    eff = aggregate_psi(isoforms)
    assert 0.5 < eff.kcat_scale < 1.0

    net, ids = _mapk()
    mek = net.registry.get(ids["MEK"])
    vmax0 = mek.kinetics.vmax
    SplicingTransformer().apply(net, make_demo_splicing_profile())
    assert net.registry.get(ids["MEK"]).kinetics.vmax != vmax0


def test_parse_psi_matrix() -> None:
    profile = parse_psi_matrix(
        [
            {"gene": "ERK", "isoform": "a", "psi": 0.6, "catalytic_efficiency": 1.0},
            {"gene": "ERK", "isoform": "b", "psi": 0.4, "catalytic_efficiency": 0.5},
        ]
    )
    assert profile.genes() == ["ERK"]
    assert len(profile.isoforms) == 2


def test_ptm_active_fraction_and_kinetics() -> None:
    state = aggregate_ptm_state(
        "ERK",
        [
            PTMSite("ERK", "T202", PTMKind.PHOSPHORYLATION, 0.9, effect="activate"),
            PTMSite("ERK", "Y204", PTMKind.PHOSPHORYLATION, 0.8, effect="activate"),
        ],
    )
    assert state.active_fraction > state.inactive_fraction
    assert state.kcat_scale > 1.0

    net, ids = _mapk()
    egfr0 = net.registry.get(ids["EGFR"]).kinetics.degradation_rate
    PTMTransformer().apply(net, make_demo_ptm_profile())
    egfr1 = net.registry.get(ids["EGFR"]).kinetics.degradation_rate
    assert egfr1 > egfr0  # ubiquitin → degrade
    sites = net.registry.get(ids["ERK"]).modification_sites
    assert any("T202" in s.name for s in sites)


def test_fba_mass_balance_and_bounds() -> None:
    model = build_core_energy_network()
    S = model.stoichiometric_matrix()
    assert len(S) == len(model.metabolites)
    assert len(S[0]) == len(model.reactions)

    result = solve_fba(model, max_iter=6000, tol=1e-6)
    assert result.residual_norm < 5e-3
    assert result.objective_value >= 0.0
    for rxn in model.reactions:
        v = result.flux(rxn.reaction_id)
        assert rxn.lb - 1e-6 <= v <= rxn.ub + 1e-6


def test_michaelis_menten_multiplier() -> None:
    assert michaelis_menten_multiplier(0.0, floor=0.05) == pytest.approx(0.05)
    hi = michaelis_menten_multiplier(100.0, km=1.0, vmax_frac=1.0, floor=0.05)
    lo = michaelis_menten_multiplier(0.1, km=1.0, vmax_frac=1.0, floor=0.05)
    assert hi > lo
    assert hi <= 1.0 + 1e-9


def test_metabolic_coupling_changes_vmax() -> None:
    net, ids = _mapk()
    mek0 = net.registry.get(ids["MEK"]).kinetics.vmax
    from voidsignal.omics import MetabolicCoupler

    fba, states = MetabolicCoupler().apply(net, make_demo_metabolomic_profile())
    assert fba.residual_norm < 5e-2
    assert "MEK" in states
    assert net.registry.get(ids["MEK"]).kinetics.vmax != mek0


def test_multiomics_bridge_patient_and_ode() -> None:
    net, ids = _mapk()
    patient = PatientSignalingNetwork(
        patient_id="P_OMICS",
        network=net,
        metadata={},
    )
    bridge = MultiOmicsBridge(clone=False)
    result = bridge.apply(patient, make_demo_multiomics_profile())
    assert set(result.layers_applied) == {
        "epigenomics",
        "splicing",
        "proteomics",
        "metabolomics",
    }
    assert result.fba is not None
    assert result.patient is not None
    assert "omics_layers" in result.patient.metadata

    eng = DualEngineSimulator(result.network)
    traj = eng.run_ode(SimulationConfig(t_end=12.0, dt=0.5))
    assert len(traj) >= 2
    erk = traj.final_concentrations()[ids["ERK"]]
    assert math.isfinite(erk) and erk >= 0.0


def test_multiomics_profile_partial_layers() -> None:
    net, _ = _mapk()
    profile = MultiOmicsProfile(
        sample_id="partial",
        epigenomics=make_demo_epigenomic_profile(),
        proteomics=None,
        splicing=None,
        metabolomics=None,
    )
    result = MultiOmicsBridge().apply(net, profile)
    assert result.layers_applied == ["epigenomics"]
    assert result.transcription_scales
    assert not result.ptm_states
