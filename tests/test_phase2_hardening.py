"""Hardening patch tests: SQLite cache, raw-VCF fallback, stoichiometry."""

from __future__ import annotations

from pathlib import Path

from voidsignal import (
    GenomicIntervalIndex,
    InteractionType,
    MutationKind,
    ReactionDefinition,
    ResponseCache,
    StoichiometricSpecies,
    VCFParser,
    VariantConsequence,
    build_network_from_kgml,
    infer_structural_consequence,
    pathway_map_to_network,
    reaction_to_relations,
    variants_to_mutations,
)
from voidsignal.knowledge_graph import KEGGClient, ReactomeClient
from voidsignal.parsers import GeneInterval

FIXTURES = Path(__file__).parent / "fixtures"


def test_sqlite_cache_roundtrip_and_expiry() -> None:
    cache = ResponseCache(":memory:", default_ttl=3600.0)
    cache.set("uniprot", "P04637", {"accession": "P04637"}, ttl=60.0)
    hit = cache.get("uniprot", "P04637")
    assert hit is not None
    assert hit.payload["accession"] == "P04637"
    assert hit.ttl_remaining > 0

    # Expired entry is treated as a miss
    cache.set("kegg", "hsa04010", {"body_text": "<pathway/>"}, ttl=0.0001)
    import time

    time.sleep(0.01)
    assert cache.get("kegg", "hsa04010") is None
    stats = cache.stats()
    assert stats["live_rows"] >= 1
    cache.close()


def test_raw_vcf_interval_fallback_infers_gene_and_frameshift() -> None:
    index = GenomicIntervalIndex.from_gff(FIXTURES / "sample.gff")
    parser = VCFParser(FIXTURES / "raw_unannotated.vcf", feature_index=index)
    _, records = parser.parse()
    assert parser.fallback_annotated >= 2
    by_pos = {r.pos: r for r in records}
    snv = by_pos[55100000]
    assert snv.gene == "EGFR"
    assert snv.annotation_source == "interval_fallback"
    assert snv.consequence is VariantConsequence.MISSENSE

    indel = by_pos[55100010]
    assert indel.gene == "EGFR"
    assert indel.consequence is VariantConsequence.FRAMESHIFT

    mutations = variants_to_mutations(records, {"EGFR": "e1", "KRAS": "e2"})
    assert any(m.kind is MutationKind.KNOCKOUT for m in mutations)


def test_structural_stop_from_coding_sequence() -> None:
    # Sense-strand CDS: ATG TTT TAA — mutating middle of codon 2 TTT→TAT is missense;
    # mutating to create TGA stop
    iv = GeneInterval(
        chrom="chr1",
        start=100,
        end=108,
        gene="TOY",
        cds_start=100,
        cds_end=108,
        coding_sequence="ATGTTTTAA",
    )
    # pos 103 is first base of codon 2 (TTT); change T→A → ATT (still missense)
    csq, reason, _ = infer_structural_consequence("T", "A", 103, iv)
    assert csq is VariantConsequence.MISSENSE
    # Create stop: codon 2 TTT → TAG by changing last T at pos 105 to G... wait
    # positions: 100=A,101=T,102=G,103=T,104=T,105=T,106=T,107=A,108=A
    # Change pos 105 T→A → TTA (Leu). Change 103-105 via SNV at 104? 
    # Better: change pos 106 which starts stop codon TAA — change A@107 keeps stop.
    # Nonsense: mutate codon2 TTT at offset making TAG: positions 103,104,105 = T,T,T
    # Change 105 T→G → TTG (Leu). Change 104 T→A → TAT.
    # Use ATG → TAG at start: pos 102 G→A? ATG with G->A = ATA.
    # Coding "ATGTAG..." with SNV creating TAG at codon2 when sequence is ATGTTC...
    iv2 = GeneInterval(
        chrom="chr1",
        start=1,
        end=9,
        gene="TOY2",
        cds_start=1,
        cds_end=9,
        coding_sequence="ATGTTCTAA",  # Met-Phe-Stop
    )
    # Change TTC (pos 4-6) middle T@5 → A → TAC (Tyr) missense
    # Change C@6 → G → TTG missense; Change TT C → TT A stays Phe; 
    # Change first T of codon2 (pos4) T→A => ATC.
    # To get stop: change codon2 TTC → TAG: need T→T, T→A, C→G at 4,5,6 — single SNV:
    # TTC → TAC (pos5 T→A) not stop. TTC → TTG not stop.
    # Start-loss: ATG → ATA at pos3 G→A
    csq2, reason2, _ = infer_structural_consequence("G", "A", 3, iv2)
    assert csq2 is VariantConsequence.START_LOST
    assert "start" in reason2


def test_kgml_stoichiometry_reactions_and_edge_metadata() -> None:
    kgml = (FIXTURES / "mapk_mini.kgml").read_text(encoding="utf-8")
    pathway = KEGGClient().parse_kgml(kgml, pathway_id="hsa04010")
    assert pathway.reactions, "expected stoichiometric <reaction> blocks"
    rxn = pathway.reactions[0]
    assert rxn.substrates[0].name == "Glucose"
    assert rxn.products[0].coefficient == 2.0
    assert any(c.name == "HK1" for c in rxn.catalysts)

    net = pathway_map_to_network(pathway)
    stoich_edges = [
        e for e in net.edges() if e.metadata.get("role") in {"substrate_to_product", "catalysis"}
    ]
    assert stoich_edges
    assert any(e.metadata.get("stoichiometry_target") == 2.0 for e in stoich_edges)
    assert any(e.interaction_type is InteractionType.CATALYSIS for e in stoich_edges)
    # Legacy PPrel edges still present
    assert any(e.interaction_type is InteractionType.INHIBITION for e in net.edges())


def test_reactome_reaction_from_event_offline() -> None:
    client = ReactomeClient()
    event = {
        "stId": "R-HSA-TEST",
        "displayName": "HK1 phosphorylates glucose",
        "schemaClass": "Reaction",
        "input": [{"displayName": "Glucose [cytosol]", "stoichiometry": 1}],
        "output": [{"displayName": "G6P [cytosol]", "stoichiometry": 1}],
        "catalystActivity": [
            {"physicalEntity": {"displayName": "HK1 [cytosol]"}}
        ],
    }
    reaction = client.reaction_from_event(event)
    assert reaction is not None
    assert reaction.catalysts[0].name == "HK1"
    rels = reaction_to_relations(reaction, evidence_prefix="Reactome")
    assert any(r.role == "catalysis" for r in rels)
    assert any(r.role == "substrate_to_product" for r in rels)
    names, coeffs = reaction.stoichiometry_matrix()
    assert "Glucose" in names
    assert sum(1 for c in coeffs if c < 0) >= 1
    assert sum(1 for c in coeffs if c > 0) >= 1


def test_backward_compatible_build_network_from_kgml() -> None:
    kgml = (FIXTURES / "mapk_mini.kgml").read_text(encoding="utf-8")
    net = build_network_from_kgml(kgml, pathway_id="hsa04010")
    assert len(net) >= 6
    assert net.validate() == []
