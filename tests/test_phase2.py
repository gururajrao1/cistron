"""Phase 2 tests — parsers, KGML→network, VCF→Mutation, ETL missingness."""

from __future__ import annotations

from pathlib import Path

import pytest

from voidsignal import (
    BioDataPipeline,
    DualEngineSimulator,
    InteractionType,
    LocalDataset,
    MutationKind,
    PPIEdge,
    PublicReferences,
    SignalingNetwork,
    SimulationConfig,
    VariantConsequence,
    approximate_kinetics,
    build_network_from_kgml,
    consequence_to_mapping,
    degree_centrality,
    normalize_consequence,
    variants_to_mutations,
)
from voidsignal.knowledge_graph import KEGGClient, apply_ppi_edges
from voidsignal.parsers import BEDParser, FASTAParser, GFFParser, VCFParser

FIXTURES = Path(__file__).parent / "fixtures"


def test_vcf_parser_and_consequence_mapping() -> None:
    header, records = VCFParser(FIXTURES / "sample.vcf").parse()
    assert header.fileformat == "VCFv4.2"
    assert len(records) == 5

    missense_egfr = next(
        r for r in records if r.gene == "EGFR" and r.consequence is VariantConsequence.MISSENSE
    )
    assert missense_egfr.pos == 55249071
    kras = next(r for r in records if r.gene == "KRAS")
    tp53 = next(r for r in records if r.gene == "TP53")
    assert kras.consequence is VariantConsequence.STOP_GAINED
    assert tp53.consequence is VariantConsequence.FRAMESHIFT

    loF = consequence_to_mapping(VariantConsequence.STOP_GAINED)
    assert loF.kind is MutationKind.KNOCKOUT
    assert not loF.skip

    silent = consequence_to_mapping(VariantConsequence.SYNONYMOUS)
    assert silent.skip


def test_variants_to_mutations_stop_is_knockout() -> None:
    _, records = VCFParser(FIXTURES / "sample.vcf").parse()
    # Minimal network index
    gene_to_id = {"EGFR": "e1", "BRAF": "e2", "KRAS": "e3", "TP53": "e4"}
    mutations = variants_to_mutations(records, gene_to_id)
    kinds = {m.name: m.kind for m in mutations}
    # synonymous LowQual EGFR should be skipped (filtered + silent)
    assert any(k is MutationKind.KNOCKOUT for k in kinds.values())
    assert any(k is MutationKind.HYPOMORPH for k in kinds.values())
    kras_mut = next(m for m in mutations if "KRAS" in m.name or m.target_id == "e3")
    assert kras_mut.kind is MutationKind.KNOCKOUT
    assert kras_mut.permanent_lock


def test_fasta_gff_bed_parsers() -> None:
    fasta = FASTAParser(FIXTURES / "sample.fasta").as_dict()
    assert "EGFR" in fasta
    assert fasta["EGFR"].length == 14
    assert 0.0 <= fasta["EGFR"].gc_content() <= 1.0

    features = GFFParser(FIXTURES / "sample.gff").parse()
    assert any(f.gene_name == "BRAF" for f in features)
    genes = GFFParser(FIXTURES / "sample.gff").gene_spans()
    assert "KRAS" in genes

    intervals = BEDParser(FIXTURES / "sample.bed").parse()
    assert intervals[0].name == "EGFR"
    assert intervals[0].length == 55211628 - 55019016


def test_kgml_to_signaling_network() -> None:
    kgml = (FIXTURES / "mapk_mini.kgml").read_text(encoding="utf-8")
    net = build_network_from_kgml(kgml, pathway_id="hsa04010")
    names = {e.name for e in net.registry.entities()}
    assert {"EGF", "EGFR", "KRAS", "BRAF"}.issubset(names)
    # MEK / ERK labels come from graphics name first token
    assert any(n.startswith("MAP2K1") or n == "MAP2K1" for n in names)
    assert any(n.startswith("MAPK1") or n == "MAPK1" for n in names)
    assert len(net.edges()) >= 5
    types = {e.interaction_type for e in net.edges()}
    assert InteractionType.PHOSPHORYLATION in types
    assert InteractionType.INHIBITION in types
    loops = net.detect_feedback_loops()
    assert loops
    issues = net.validate()
    assert issues == []


def test_string_weight_overlay_and_missingness_kinetics() -> None:
    kgml = (FIXTURES / "mapk_mini.kgml").read_text(encoding="utf-8")
    net = build_network_from_kgml(kgml, pathway_id="hsa04010")
    edges = [
        PPIEdge(protein_a="EGFR", protein_b="KRAS", score=0.9, evidence="STRING"),
        PPIEdge(protein_a="KRAS", protein_b="BRAF", score=0.8, evidence="STRING"),
    ]
    added = apply_ppi_edges(net, edges, min_score=0.4, create_missing=False)
    assert added >= 2

    cents = degree_centrality(net)
    assert all(0.0 <= v <= 1.0 for v in cents.values())

    params = approximate_kinetics(degree_cent=0.8, string_weight=0.9, sequence_length=400)
    assert params.production_rate > 0.05
    assert 0.01 <= params.degradation_rate <= 0.5


def test_pipeline_offline_etl_maps_vcf_mutations() -> None:
    """Full ETL without live HTTP: local files + offline KGML seed network."""
    kgml = (FIXTURES / "mapk_mini.kgml").read_text(encoding="utf-8")
    seed = build_network_from_kgml(kgml, pathway_id="hsa04010")

    # Alias MEK/ERK style names already in network; add TP53 for frameshift mapping
    from voidsignal import Protein

    if not any(e.name == "TP53" for e in seed.registry.entities()):
        seed.add_node(Protein(name="TP53", concentration=0.1))

    pipeline = BioDataPipeline()
    dataset = LocalDataset(
        vcf_path=FIXTURES / "sample.vcf",
        fasta_path=FIXTURES / "sample.fasta",
        gff_path=FIXTURES / "sample.gff",
        bed_path=FIXTURES / "sample.bed",
        gene_panel=["EGFR", "BRAF", "KRAS", "TP53"],
    )
    refs = PublicReferences(
        kegg_pathway_id=None,
        use_string=False,
        use_biogrid=False,
        enrich_uniprot=False,
    )
    result = pipeline.run_sync(dataset, refs, base_network=seed, uniprot_max_genes=0)

    assert result.metadata["n_nodes"] >= 5
    assert len(result.variants) == 5
    assert any(m.kind is MutationKind.KNOCKOUT for m in result.mutations)
    # BED metadata stamped
    egfr = next(e for e in result.network.registry.entities() if e.name == "EGFR")
    assert egfr.metadata.get("bed_chrom") == "chr7"
    # Missingness fallback should fire (no UniProt)
    assert len(result.missingness) >= 1
    assert all(r.assigned_production_rate > 0 for r in result.missingness)

    # Mutations must be runnable in DualEngineSimulator
    engine = DualEngineSimulator(result.network)
    traj = engine.run_boolean(
        SimulationConfig(boolean_steps=5, dt=1.0),
        perturbation_hooks=result.perturbation_manager().hooks(),
    )
    assert len(traj) >= 2


def test_normalize_consequence_severity() -> None:
    assert normalize_consequence("missense_variant&splice_acceptor_variant") is (
        VariantConsequence.SPLICE_ACCEPTOR
    )


def test_kegg_client_parse_kgml_unit() -> None:
    kgml = (FIXTURES / "mapk_mini.kgml").read_text(encoding="utf-8")
    pathway = KEGGClient().parse_kgml(kgml, pathway_id="hsa04010")
    assert pathway.name == "MAPK signaling pathway"
    assert "EGFR" in pathway.nodes
    assert any(r.interaction_type is InteractionType.INHIBITION for r in pathway.relations)
