"""Bridge patch: stoichiometric ODE RHS + vendored MAPK offline pathway."""

from __future__ import annotations

from cistron import (
    DualEngineSimulator,
    InteractionType,
    KineticParameters,
    MassActionRHS,
    Protein,
    PublicReferences,
    SignalingNetwork,
    SimulationConfig,
    VendoredPathwayRepository,
    build_network_from_kgml,
    pathway_map_to_network,
)
from cistron.knowledge_graph import (
    PathwayMap,
    PathwayRelation,
    ReactionDefinition,
    StoichiometricSpecies,
    reaction_to_relations,
)
from cistron.pipeline import BioDataPipeline, LocalDataset


def test_stoichiometric_mass_action_flux_scales_products() -> None:
    """
    Reaction: 1·A + enzyme E → 2·B
    Mass balance requires ΔB ≈ −2 · ΔA (modulo basal production/degradation).
    """
    net = SignalingNetwork(name="stoich")
    a = Protein(
        name="A",
        concentration=2.0,
        kinetics=KineticParameters(production_rate=0.0, degradation_rate=0.0),
    )
    b = Protein(
        name="B",
        concentration=0.0,
        kinetics=KineticParameters(production_rate=0.0, degradation_rate=0.0),
    )
    e = Protein(
        name="E",
        concentration=1.0,
        kinetics=KineticParameters(production_rate=0.0, degradation_rate=0.0),
    )
    net.add_node(a)
    net.add_node(b)
    net.add_node(e)

    reaction = ReactionDefinition(
        reaction_id="r1",
        name="A_to_2B",
        substrates=[StoichiometricSpecies("A", 1.0, "substrate")],
        products=[StoichiometricSpecies("B", 2.0, "product")],
        catalysts=[StoichiometricSpecies("E", 1.0, "catalyst")],
    )
    # Map names → use entity names matching reaction_to_relations then reconnect ids
    # Build edges manually with correct entity ids
    for rel in reaction_to_relations(reaction):
        src = {"A": a.entity_id, "B": b.entity_id, "E": e.entity_id}[rel.source]
        tgt = {"A": a.entity_id, "B": b.entity_id, "E": e.entity_id}[rel.target]
        net.connect(
            src,
            tgt,
            rel.interaction_type,
            rate_constant=0.5,
            weight=1.0,
            metadata={
                "role": rel.role,
                "reaction_id": "r1",
                "stoichiometry_source": rel.stoichiometry_source,
                "stoichiometry_target": rel.stoichiometry_target,
                **rel.metadata,
            },
        )

    rhs = MassActionRHS(net)
    assert len(rhs.compiled_reactions) >= 1
    compiled = rhs.compiled_reactions[0]
    assert compiled.products[b.entity_id] == 2.0
    assert a.entity_id in compiled.substrates

    y0 = rhs.pack()
    dydt = rhs(0.0, y0)
    idx = {nid: i for i, nid in enumerate(rhs.species)}
    dA = dydt[idx[a.entity_id]]
    dB = dydt[idx[b.entity_id]]
    # dB/dt should be ≈ −2 · dA/dt for this irreversible reaction
    assert dA < 0.0
    assert dB > 0.0
    assert abs(dB + 2.0 * dA) < 1e-9

    engine = DualEngineSimulator(net)
    traj = engine.run_ode(SimulationConfig(t_end=1.0, dt=0.05, record_every=5))
    final = traj.final_concentrations()
    assert final[a.entity_id] < 2.0
    assert final[b.entity_id] > 0.0
    # Approximate conservation: 2*A + B ≈ constant (= 4 at t0)
    conserv0 = 2.0 * 2.0 + 0.0
    conserv1 = 2.0 * final[a.entity_id] + final[b.entity_id]
    assert abs(conserv1 - conserv0) < 0.15  # RK4 + discrete steps tolerance


def test_default_stoich_coefficient_one_for_legacy_edges() -> None:
    net = SignalingNetwork()
    src = Protein(name="SRC", concentration=1.0, kinetics=KineticParameters(degradation_rate=0.0, production_rate=0.0))
    tgt = Protein(name="TGT", concentration=0.0, kinetics=KineticParameters(degradation_rate=0.0, production_rate=0.0))
    net.add_node(src)
    net.add_node(tgt)
    net.connect(src.entity_id, tgt.entity_id, InteractionType.ACTIVATION, rate_constant=1.0)
    rhs = MassActionRHS(net)
    assert rhs.compiled_reactions == []
    dydt = rhs(0.0, rhs.pack())
    # Legacy path still drives target upward
    assert dydt[rhs.species.index(tgt.entity_id)] > 0.0


def test_vendored_mapk_loads_offline_with_reactions() -> None:
    repo = VendoredPathwayRepository()
    assert repo.has("hsa04010")
    pathway = repo.load_map("hsa04010")
    assert pathway.metadata.get("vendored") is True
    assert pathway.reactions
    assert "EGFR" in pathway.nodes or any("EGFR" in n for n in pathway.nodes)
    net = repo.load_network("hsa04010")
    assert len(net) >= 6
    assert any(e.metadata.get("role") == "substrate_to_product" for e in net.edges())
    rhs = MassActionRHS(net)
    assert len(rhs.compiled_reactions) >= 1


def test_pipeline_prefer_vendored_skips_api() -> None:
    pipeline = BioDataPipeline()
    result = pipeline.run_sync(
        LocalDataset(gene_panel=["EGFR", "KRAS"]),
        PublicReferences(
            kegg_pathway_id="hsa04010",
            prefer_vendored=True,
            use_string=False,
            enrich_uniprot=False,
        ),
        uniprot_max_genes=0,
    )
    assert result.metadata["n_nodes"] >= 6
    assert any(
        e.metadata.get("stoichiometry_target") for e in result.network.edges()
    )


def test_safe_power_handles_near_zero() -> None:
    from cistron.simulation import _safe_power

    assert _safe_power(0.0, 2.0) >= 0.0
    assert _safe_power(1e-20, 3.0) > 0.0
    assert _safe_power(2.0, 0.0) == 1.0
