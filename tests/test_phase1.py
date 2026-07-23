"""Phase 1 unit tests for the CISTRON core engine."""

from __future__ import annotations

import math

import pytest

from cistron import (
    ActivityState,
    BooleanSimulator,
    CellularCompartment,
    Complex,
    DrugPerturbation,
    DualEngineSimulator,
    Gene,
    InhibitionModel,
    InteractionType,
    KineticParameters,
    Ligand,
    LogicGate,
    Mutation,
    MutationKind,
    NodeLogic,
    ODESimulator,
    ODEStepper,
    PerturbationManager,
    Protein,
    RNA,
    Receptor,
    SignalingNetwork,
    SimulationConfig,
)


def _linear_cascade() -> tuple[SignalingNetwork, dict[str, str]]:
    net = SignalingNetwork(name="lin")
    ids: dict[str, str] = {}
    for name, conc, on in (("A", 1.0, True), ("B", 0.0, False), ("C", 0.0, False)):
        p = Protein(name=name, concentration=conc)
        p.set_boolean(on)
        net.add_node(p, logic=NodeLogic(gate=LogicGate.OR))
        ids[name] = p.entity_id
    net.connect(ids["A"], ids["B"], InteractionType.ACTIVATION, rate_constant=1.0)
    net.connect(ids["B"], ids["C"], InteractionType.ACTIVATION, rate_constant=1.0)
    return net, ids


def test_entity_dual_state_and_kinetics() -> None:
    params = KineticParameters(production_rate=0.2, degradation_rate=0.1, basal_activity=0.25)
    protein = Protein(name="ERK", concentration=0.0, kinetics=params, is_enzyme=True)
    protein.set_boolean(True)
    protein.sync_concentration_from_boolean(on_level=2.0)
    assert protein.concentration == 2.0
    protein.set_concentration(0.1)
    protein.sync_boolean_from_concentration(threshold=0.5)
    assert protein.boolean_state is ActivityState.OFF
    updated = params.with_updates(production_rate=0.5)
    assert updated.production_rate == 0.5
    assert params.production_rate == 0.2


def test_gene_rna_protein_chain_and_compartment() -> None:
    cyto = CellularCompartment(name="cytosol", volume=1.5)
    gene = Gene(name="TP53", transcription_rate=1.2, promoter_strength=0.8)
    gene.set_boolean(True)
    rna = RNA(name="TP53_mRNA", source_gene_id=gene.entity_id, half_life=1.0)
    prot = Protein(name="p53", source_rna_id=rna.entity_id, compartment_id=cyto.compartment_id)
    net = SignalingNetwork()
    net.registry.register_compartment(cyto)
    net.add_node(gene)
    net.add_node(rna)
    net.add_node(prot)
    assert gene.effective_transcription_rate() > 0.0
    assert rna.kinetics.degradation_rate == pytest.approx(math.log(2.0) / 1.0)
    assert prot.entity_id in cyto.resident_ids


def test_complex_ligand_receptor() -> None:
    r = Receptor(name="EGFR", concentration=1.0, cognate_ligand_ids=set())
    lig = Ligand(name="EGF", concentration=2.0, kd=1.0)
    r.cognate_ligand_ids.add(lig.entity_id)
    signal = r.bind_ligand(lig)
    assert 0.0 < r.bound_fraction < 1.0
    assert signal == pytest.approx(r.active_signal())
    c = Complex(name="dimer", members={r.entity_id: 2.0}, association_rate=0.5)
    c.add_member(lig.entity_id, 1.0)
    assert lig.entity_id in c.members


def test_topology_hubs_feedback_robustness() -> None:
    net = SignalingNetwork()
    ids = {}
    for name in ("X", "Y", "Z"):
        p = Protein(name=name, concentration=0.5)
        net.add_node(p)
        ids[name] = p.entity_id
    net.connect(ids["X"], ids["Y"], InteractionType.ACTIVATION)
    net.connect(ids["Y"], ids["Z"], InteractionType.ACTIVATION)
    net.connect(ids["Z"], ids["X"], InteractionType.INHIBITION)
    loops = net.detect_feedback_loops()
    assert loops
    hubs = net.find_hubs(2)
    assert hubs[0][1] >= hubs[1][1]
    rob = net.robustness(ids["Z"])
    assert "mean_retention" in rob
    assert 0.0 <= rob["mean_retention"] <= 1.0
    order, matrix = net.adjacency_matrix()
    assert len(order) == 3
    assert len(matrix) == 3


def test_boolean_propagation_and_knockout() -> None:
    net, ids = _linear_cascade()
    sim = BooleanSimulator(net)
    for _ in range(3):
        sim.step()
    assert net.registry.get(ids["C"]).boolean_state is ActivityState.ON

    mut = Mutation(target_id=ids["B"], kind=MutationKind.KNOCKOUT, t_start=0.0)
    engine = DualEngineSimulator(net)
    engine.run_boolean(
        SimulationConfig(boolean_steps=5, dt=1.0),
        perturbation_hooks=[mut.as_hook()],
    )
    assert net.registry.get(ids["B"]).boolean_state is ActivityState.OFF
    assert net.registry.get(ids["B"]).concentration == 0.0


def test_ode_rk4_nonnegative_and_attractor_api() -> None:
    net, ids = _linear_cascade()
    for eid in ids.values():
        net.registry.get(eid).kinetics = KineticParameters(
            production_rate=0.0,
            degradation_rate=0.05,
            basal_activity=0.0,
        )
    net.registry.get(ids["A"]).set_concentration(1.0)
    traj = ODESimulator(net).run(
        SimulationConfig(t_end=5.0, dt=0.1, stepper=ODEStepper.RK4, record_every=5)
    )
    assert len(traj) >= 2
    for sample in traj.concentrations:
        for value in sample.values():
            assert value >= -1e-9
    # B should rise from A drive
    assert traj.final_concentrations()[ids["B"]] > 0.0


def test_drug_inhibition_models() -> None:
    competitive = DrugPerturbation(
        target_id="dummy",
        model=InhibitionModel.COMPETITIVE,
        ki=1.0,
        km=1.0,
        concentration=1.0,
    )
    # Build minimal network so apply works
    net = SignalingNetwork()
    target = Protein(name="MEK", concentration=1.0, kinetics=KineticParameters(production_rate=1.0, vmax=2.0))
    net.add_node(target)
    competitive.target_id = target.entity_id
    factor = competitive.inhibition_factor(1.0, substrate_conc=1.0)
    assert 0.0 < factor < 1.0
    nc = DrugPerturbation(
        target_id=target.entity_id,
        model=InhibitionModel.NONCOMPETITIVE,
        ki=1.0,
        concentration=1.0,
    )
    assert nc.inhibition_factor(1.0) == pytest.approx(0.5)

    mgr = PerturbationManager()
    mgr.dose(target.entity_id, concentration=5.0, ki=0.5, t_start=0.0)
    engine = DualEngineSimulator(net)
    traj = engine.run_ode(SimulationConfig(t_end=2.0, dt=0.1), perturbation_hooks=mgr.hooks())
    assert traj.metadata["n_steps"] > 0


def test_export_columnar_and_hybrid() -> None:
    net, ids = _linear_cascade()
    engine = DualEngineSimulator(net)
    bcfg = SimulationConfig(boolean_steps=5, dt=1.0)
    ocfg = SimulationConfig(t_end=2.0, dt=0.2, record_every=2)
    btraj, otraj = engine.boolean_then_ode(bcfg, ocfg)
    cols = otraj.to_columnar()
    assert "time" in cols
    assert ids["A"] in cols
