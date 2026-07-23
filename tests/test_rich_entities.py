"""Tests for rich biological entities, crosstalk topology, and causal reasoner (v0.17)."""

from __future__ import annotations

import copy

import pytest

from cistron import (
    CausalBioReasoner,
    ClinicalAnnotation,
    DrugAssociation,
    Gene,
    InteractionType,
    KineticParameters,
    ModificationType,
    ODESimulator,
    Protein,
    ProteinDomain,
    SignalingNetwork,
    SimulationConfig,
    StructuralMetadata,
    __version__,
)
from cistron.simulation import SimulatorBackend, TrajectoryResult


def test_version_bump() -> None:
    assert __version__ == "0.21.0"


def _rich_egfr() -> Protein:
    return Protein(
        name="EGFR",
        gene_symbol="EGFR",
        full_name="Epidermal growth factor receptor",
        uniprot_id="P00533",
        kegg_id="hsa:1956",
        aliases=["ERBB1", "HER1"],
        concentration=1.0,
        is_enzyme=True,
        cellular_localization="Plasma Membrane",
        domains=[
            ProteinDomain(name="kinase", start=712, end=979, domain_type="kinase"),
            ProteinDomain(name="TM", start=646, end=668, domain_type="transmembrane"),
        ],
        structure=StructuralMetadata(
            pdb_id="1M17",
            alphafold_plddt_score=86.5,
            active_site_center=(10.0, 20.0, 30.0),
            active_site_size=(12.0, 12.0, 12.0),
            disruption_delta=0.0,
        ),
        clinical=ClinicalAnnotation(
            diseases=["NSCLC", "glioblastoma"],
            somatic_mutations=["EGFR p.L858R"],
            oncogene=True,
            clinical_significance="pathogenic",
        ),
        drugs=[
            DrugAssociation(
                name="Gefitinib",
                mechanism="inhibitor",
                ic50_nM=33.0,
                approval_status="approved",
            ),
        ],
        pathway_membership=["MAPK", "PI3K-AKT"],
        kinetics=KineticParameters(
            production_rate=0.1,
            degradation_rate=0.05,
            vmax=2.0,
            km=0.5,
        ),
    )


def test_protein_encyclopedia_and_kinetics_compat() -> None:
    egfr = _rich_egfr()
    egfr.set_modification(
        "Tyr1068",
        ModificationType.PHOSPHORYLATION,
        stoichiometry=1.0,
        residue="Tyr1068",
        occupancy=0.8,
        active=True,
    )
    assert egfr.ptm_sites[0].residue == "Tyr1068"
    assert egfr.kinetics.vmax == 2.0
    assert egfr.structure.disruption_delta == 0.0

    d = egfr.to_dict()
    assert d["uniprot_id"] == "P00533"
    assert d["k_cat"] == 2.0
    assert d["Km"] == 0.5
    assert d["ptm_sites"][0]["occupancy"] == pytest.approx(0.8)
    assert d["drugs"][0]["ic50_nM"] == 33.0

    card = egfr.to_encyclopedia_card()
    assert card["card_type"] == "protein"
    assert card["identity"]["gene_symbol"] == "EGFR"
    assert card["biology"]["cellular_localization"] == "Plasma Membrane"
    assert card["structure"]["pdb_id"] == "1M17"
    assert card["clinical"]["somatic_mutations"] == ["EGFR p.L858R"]
    assert "kinetics" in card


def test_gene_encyclopedia_card() -> None:
    gene = Gene(
        name="TP53",
        gene_symbol="TP53",
        full_name="Tumor protein p53",
        uniprot_id="P04637",
        kegg_id="hsa:7157",
        aliases=["p53"],
        chromosomal_locus="chr17:7661779-7687550",
        cellular_localization="Nucleus",
        clinical=ClinicalAnnotation(
            diseases=["Li-Fraumeni"],
            somatic_mutations=["TP53 p.R175H"],
            tumor_suppressor=True,
        ),
        pathway_membership=["JAK-STAT"],
    )
    card = gene.to_encyclopedia_card()
    assert card["card_type"] == "gene"
    assert card["identity"]["uniprot_id"] == "P04637"
    assert card["clinical"]["tumor_suppressor"] is True
    assert gene.gene_symbol == "TP53"


def test_rich_metadata_persists_through_ode() -> None:
    net = SignalingNetwork(name="rich_ode")
    egfr = _rich_egfr()
    mek = Protein(
        name="MEK",
        gene_symbol="MEK",
        concentration=0.2,
        kinetics=KineticParameters(degradation_rate=0.05, vmax=1.0),
    )
    erk = Protein(
        name="ERK",
        gene_symbol="ERK",
        concentration=0.1,
        kinetics=KineticParameters(degradation_rate=0.05),
    )
    net.add_node(egfr)
    net.add_node(mek)
    net.add_node(erk)
    net.connect(
        egfr.entity_id,
        mek.entity_id,
        InteractionType.PHOSPHORYLATION,
        rate_constant=1.0,
    )
    net.connect(
        mek.entity_id,
        erk.entity_id,
        InteractionType.PHOSPHORYLATION,
        rate_constant=1.0,
    )

    pre_card = egfr.to_encyclopedia_card()
    traj = ODESimulator(net).run(SimulationConfig(t_end=2.0, dt=0.1, record_every=2))
    assert len(traj) >= 2
    post = net.registry.get(egfr.entity_id)
    assert isinstance(post, Protein)
    assert post.uniprot_id == "P00533"
    assert post.drugs[0].name == "Gefitinib"
    assert post.to_encyclopedia_card()["identity"] == pre_card["identity"]
    assert traj.final_concentrations()[mek.entity_id] >= 0.0


def _multi_pathway_net() -> tuple[SignalingNetwork, dict[str, str]]:
    net = SignalingNetwork(name="crosstalk")
    ids: dict[str, str] = {}
    specs = [
        ("EGFR", ["MAPK", "PI3K-AKT"]),
        ("RAS", ["MAPK", "PI3K-AKT"]),
        ("RAF", ["MAPK"]),
        ("MEK", ["MAPK"]),
        ("ERK", ["MAPK"]),
        ("PI3K", ["PI3K-AKT"]),
        ("AKT", ["PI3K-AKT"]),
        ("JAK", ["JAK-STAT"]),
        ("STAT", ["JAK-STAT"]),
        ("TP53", ["JAK-STAT"]),
    ]
    for name, pathways in specs:
        p = Protein(
            name=name,
            gene_symbol=name,
            concentration=0.5,
            pathway_membership=list(pathways),
        )
        net.add_node(p)
        ids[name] = p.entity_id

    net.connect(ids["EGFR"], ids["RAS"], InteractionType.ACTIVATION)
    net.connect(ids["RAS"], ids["RAF"], InteractionType.ACTIVATION)
    net.connect(ids["RAF"], ids["MEK"], InteractionType.PHOSPHORYLATION)
    net.connect(ids["MEK"], ids["ERK"], InteractionType.PHOSPHORYLATION)
    net.connect(ids["EGFR"], ids["PI3K"], InteractionType.ACTIVATION)
    net.connect(ids["RAS"], ids["PI3K"], InteractionType.ACTIVATION)
    net.connect(ids["PI3K"], ids["AKT"], InteractionType.ACTIVATION)
    net.connect(ids["JAK"], ids["STAT"], InteractionType.PHOSPHORYLATION)
    net.connect(ids["ERK"], ids["TP53"], InteractionType.ACTIVATION)
    net.connect(ids["STAT"], ids["TP53"], InteractionType.ACTIVATION)
    return net, ids


def test_multi_pathway_crosstalk_hubs_and_switches() -> None:
    net, ids = _multi_pathway_net()
    assigned = net.auto_annotate_canonical_pathways()
    assert "MAPK" in assigned
    assert "PI3K-AKT" in assigned
    assert ids["EGFR"] in assigned["MAPK"]
    assert ids["EGFR"] in assigned["PI3K-AKT"]

    hubs = net.get_hub_nodes(top_k=3)
    assert hubs
    assert hubs[0]["degree"] >= hubs[-1]["degree"]

    bottlenecks = net.get_bottlenecks(top_k=3)
    assert bottlenecks
    assert "betweenness" in bottlenecks[0]

    bridges = net.detect_crosstalk(
        net.pathway_nodes("MAPK"),
        net.pathway_nodes("PI3K-AKT"),
    )
    assert bridges
    assert any(e.source_id == ids["RAS"] and e.target_id == ids["PI3K"] for e in bridges)

    switches = net.detect_crosstalk_switches()
    switch_ids = {s["entity_id"] for s in switches}
    assert ids["EGFR"] in switch_ids
    assert ids["RAS"] in switch_ids
    egfr_sw = next(s for s in switches if s["entity_id"] == ids["EGFR"])
    assert set(egfr_sw["pathways"]) >= {"MAPK", "PI3K-AKT"}


def _fake_traj(finals: dict[str, float]) -> TrajectoryResult:
    return TrajectoryResult(
        times=[0.0, 1.0],
        concentrations=[{k: 0.1 for k in finals}, dict(finals)],
        boolean_states=[{k: 0 for k in finals}, {k: 1 for k in finals}],
        backend=SimulatorBackend.ODE,
    )


def test_causal_activation_and_inactivation_narratives() -> None:
    net, ids = _multi_pathway_net()
    net.auto_annotate_canonical_pathways()

    ras = net.registry.get(ids["RAS"])
    assert isinstance(ras, Protein)
    ras.clinical = ClinicalAnnotation(
        somatic_mutations=["KRAS p.G12D"],
        oncogene=True,
    )

    pi3k = net.registry.get(ids["PI3K"])
    assert isinstance(pi3k, Protein)
    pi3k.drugs = [
        DrugAssociation(name="Wortmannin", mechanism="inhibitor", ic50_nM=5.0),
    ]

    control = _fake_traj(
        {
            ids["ERK"]: 0.4,
            ids["AKT"]: 0.5,
            ids["RAS"]: 0.3,
            ids["MEK"]: 0.3,
            ids["PI3K"]: 0.4,
            ids["EGFR"]: 0.5,
            ids["RAF"]: 0.3,
            ids["JAK"]: 0.2,
            ids["STAT"]: 0.2,
            ids["TP53"]: 0.2,
        }
    )
    perturbed = _fake_traj(
        {
            ids["ERK"]: 0.85,
            ids["AKT"]: 0.05,
            ids["RAS"]: 0.9,
            ids["MEK"]: 0.7,
            ids["PI3K"]: 0.05,
            ids["EGFR"]: 0.5,
            ids["RAF"]: 0.6,
            ids["JAK"]: 0.2,
            ids["STAT"]: 0.2,
            ids["TP53"]: 0.25,
        }
    )

    attributions = {ids["RAS"]: 0.9, ids["MEK"]: 0.5, ids["PI3K"]: 0.8}
    reasoner = CausalBioReasoner(
        net,
        control,
        perturbed,
        attributions=attributions,
        activation_threshold_pct=20.0,
    )

    act = reasoner.explain_activation(ids["ERK"])
    assert act.kind == "activation"
    assert act.percent_change > 100.0
    assert "ERK" in act.narrative
    assert "G12D" in act.narrative or "GTP" in act.narrative
    assert act.chain

    ina = reasoner.explain_inactivation(ids["AKT"])
    assert ina.kind == "inactivation"
    assert "Wortmannin" in ina.narrative
    assert "inactive" in ina.narrative.lower() or "suppressed" in ina.narrative.lower()

    summary = reasoner.delta_summary()
    assert summary.activated
    assert any(e.node_name == "ERK" for e in summary.activated)
    assert summary.inactivated
    assert "Control" in summary.overview_narrative
    payload = summary.as_dict()
    assert "activated" in payload and "inactivated" in payload


def test_backward_compat_minimal_protein_constructor() -> None:
    """Existing call sites that only pass name/concentration must still work."""
    p = Protein(name="MEK", concentration=0.5)
    assert p.gene_symbol == "MEK"
    assert p.domains == []
    assert p.drugs == []
    assert p.structure.pdb_id is None
    g = Gene(name="MYC")
    assert g.gene_symbol == "MYC"
    card = copy.deepcopy(p.to_encyclopedia_card())
    assert card["title"] == "MEK"
