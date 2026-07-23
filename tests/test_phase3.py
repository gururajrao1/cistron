"""Phase 3 — structure, dogma delays, spatial compartments."""

from __future__ import annotations

import math

from voidsignal import (
    BindingPocket,
    CentralDogmaEngine,
    CompartmentTier,
    DelayLine,
    DualEngineSimulator,
    Gene,
    InteractionType,
    KineticParameters,
    MassActionRHS,
    Protein,
    RNA,
    Receptor,
    SignalingNetwork,
    SimulationConfig,
    SpatialCompartmentModel,
    StructuralDomain,
    StructuralMap,
    StructureAwareModulator,
    TransportLink,
    delay_from_length,
    degradation_rate_from_half_life,
)
from voidsignal.parsers import VariantConsequence


def test_structure_pocket_hit_scales_kinetics() -> None:
    smap = StructuralMap(
        protein_id="EGFR",
        sequence_length=1210,
        domains=[StructuralDomain("Kinase", 712, 979, kind="catalytic")],
        pockets=[BindingPocket("ATP", residues=(745, 746, 747), radius_angstrom=5.0)],
    )
    mod = StructureAwareModulator()
    mod.register(smap)

    pocket_hit, scales_pocket = mod.evaluate_variant("EGFR", 746)
    surface, scales_surface = mod.evaluate_variant("EGFR", 50)

    assert pocket_hit.disruption > surface.disruption
    assert scales_pocket.kcat_scale < scales_surface.kcat_scale
    assert scales_pocket.km_scale > 1.0

    net = SignalingNetwork()
    egfr = Protein(
        name="EGFR",
        concentration=1.0,
        kinetics=KineticParameters(vmax=2.0, km=1.0, binding_affinity=1.0, production_rate=0.2),
        metadata={"uniprot_accession": "EGFR"},
    )
    net.add_node(egfr)
    mod.apply_variant_to_network(net, "EGFR", 746, consequence=VariantConsequence.MISSENSE)
    assert egfr.kinetics.vmax < 2.0
    assert egfr.kinetics.km > 1.0
    assert egfr.metadata["structure_disruption"] > 0.5


def test_dogma_delay_line_and_half_lives() -> None:
    assert delay_from_length(1000, rate_per_unit=200.0) > delay_from_length(100, rate_per_unit=200.0)
    k = degradation_rate_from_half_life(2.0)
    assert abs(k - math.log(2.0) / 2.0) < 1e-12

    line = DelayLine(delay=1.0)
    line.push(0.0, 0.0)
    line.push(0.5, 2.0)
    line.push(1.5, 4.0)
    # t−τ ≤ 0.4 → only the sample at 0.0 is visible
    assert line.get(1.4, default=-1.0) == 0.0
    assert line.get(1.5) == 2.0
    assert line.get(2.5) == 4.0


def test_dogma_engine_injects_delayed_transcription() -> None:
    net = SignalingNetwork()
    gene = Gene(name="G", transcription_rate=1.0, promoter_strength=1.0, concentration=1.0)
    gene.set_boolean(True)
    rna = RNA(name="R", source_gene_id=gene.entity_id, translation_rate=1.0, half_life=5.0, concentration=0.0)
    prot = Protein(
        name="P",
        source_rna_id=None,
        sequence_length=100,
        concentration=0.0,
        kinetics=KineticParameters(production_rate=0.0, degradation_rate=0.0),
    )
    rna.product_protein_id = prot.entity_id
    prot.source_rna_id = rna.entity_id
    gene.expressed_rna_id = rna.entity_id
    rna.metadata["sequence_length"] = 400
    net.add_node(gene)
    net.add_node(rna)
    net.add_node(prot)

    dogma = CentralDogmaEngine(
        net, nt_per_time=1000.0, aa_per_time=200.0, basal_transcription_delay=0.2
    )
    chains = dogma.discover_chains()
    assert len(chains) == 1
    assert chains[0].transcription_delay >= 0.2
    tau_tx = chains[0].transcription_delay

    rhs = MassActionRHS(net, dogma=dogma)
    # At t=0 delayed production should be ~0
    d0 = rhs(0.0, rhs.pack())
    idx = {s: i for i, s in enumerate(rhs.species)}
    assert d0[idx[rna.entity_id]] == 0.0 or d0[idx[rna.entity_id]] < 1e-9

    # Advance history past τ so the delayed transcription flux appears
    times = [i * 0.1 for i in range(1, int(tau_tx / 0.1) + 15)]
    for t in times:
        rhs(t, rhs.pack())
    d_late = rhs(times[-1], rhs.pack())
    assert d_late[idx[rna.entity_id]] > 0.0


def test_compartment_barrier_requires_receptor() -> None:
    net = SignalingNetwork()
    egf = Protein(name="EGF", concentration=1.0)
    egfr = Receptor(name="EGFR", concentration=1.0, cognate_ligand_ids=set())
    ras = Protein(name="KRAS", concentration=0.5)
    net.add_node(egf)
    net.add_node(egfr)
    net.add_node(ras)
    # Illegal: extracellular EGF → cytoplasmic KRAS directly
    edge_bad = net.connect(egf.entity_id, ras.entity_id, InteractionType.ACTIVATION, rate_constant=1.0)
    edge_ok = net.connect(egf.entity_id, egfr.entity_id, InteractionType.BINDING, rate_constant=1.0)

    model = SpatialCompartmentModel(net)
    model.ensure_default_tiers()
    model.assign(egf.entity_id, CompartmentTier.EXTRACELLULAR)
    model.assign(egfr.entity_id, CompartmentTier.PLASMA_MEMBRANE)
    model.assign(ras.entity_id, CompartmentTier.CYTOPLASM)
    viol = model.validate_routing(autofix_slowdown=True)
    assert any(v.edge_id == edge_bad.edge_id for v in viol)
    assert net.get_edge(edge_bad.edge_id).rate_constant < 1.0
    assert net.get_edge(edge_ok.edge_id).metadata.get("spatial_class") == "gated_boundary"


def test_diffusion_transport_conserves_mass_proxy() -> None:
    net = SignalingNetwork()
    a = Protein(name="X_out", concentration=2.0, kinetics=KineticParameters(production_rate=0.0, degradation_rate=0.0))
    b = Protein(name="X_in", concentration=0.0, kinetics=KineticParameters(production_rate=0.0, degradation_rate=0.0))
    net.add_node(a)
    net.add_node(b)
    model = SpatialCompartmentModel(net)
    tiers = model.ensure_default_tiers()
    model.assign(a.entity_id, CompartmentTier.EXTRACELLULAR, tiers[CompartmentTier.EXTRACELLULAR])
    model.assign(b.entity_id, CompartmentTier.CYTOPLASM, tiers[CompartmentTier.CYTOPLASM])
    model.add_transport_link(
        TransportLink(
            entity_a=a.entity_id,
            entity_b=b.entity_id,
            compartment_a=tiers[CompartmentTier.EXTRACELLULAR],
            compartment_b=tiers[CompartmentTier.CYTOPLASM],
            permeability=0.2,
            area=1.0,
        )
    )
    rhs = MassActionRHS(net, spatial=model)
    eng = DualEngineSimulator(net, spatial=model)
    traj = eng.run_ode(SimulationConfig(t_end=5.0, dt=0.1, record_every=5))
    final = traj.final_concentrations()
    assert final[a.entity_id] < 2.0
    assert final[b.entity_id] > 0.0
    assert all(v >= -1e-9 for sample in traj.concentrations for v in sample.values())
