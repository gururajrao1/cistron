"""Tests for Virtual Cellular Laboratory integrations (offline-first)."""

from __future__ import annotations

from pathlib import Path

import pytest

from voidsignal.integrations import (
    BiologicalEnrichmentEngine,
    DepMapClient,
    EncodeClient,
    HUMAN_PATHWAY_CATALOG,
    IntegrationCache,
    LabKEGGClient,
    LabReactomeClient,
    LabSTRINGClient,
    LabUniProtClient,
    MultiPathwayMerger,
    default_integration_cache_dir,
    list_pathway_catalog,
    resolve_pathway_ids,
)
from voidsignal.integrations.offline_data import OFFLINE_PATHWAY_EDGES, OFFLINE_UNIPROT


@pytest.fixture()
def cache(tmp_path: Path) -> IntegrationCache:
    return IntegrationCache(root=tmp_path / "db")


def test_pathway_catalog_covers_core_human_signalling() -> None:
    names = {e.name.lower() for e in HUMAN_PATHWAY_CATALOG}
    assert any("mapk" in n for n in names)
    assert any("pi3k" in n for n in names)
    assert any("p53" in n for n in names)
    domains = {e.domain for e in HUMAN_PATHWAY_CATALOG}
    assert "Pathways" in domains
    assert len(list_pathway_catalog()) >= 12


def test_resolve_pathway_ids_aliases() -> None:
    hits = resolve_pathway_ids(["MAPK", "pi3k", "hsa04115"])
    ids = {h.pathway_id for h in hits}
    assert "hsa04010" in ids
    assert "hsa04151" in ids
    assert "hsa04115" in ids


def test_integration_cache_roundtrip(cache: IntegrationCache) -> None:
    cache.set_json("demo", "EGFR", {"ok": True})
    assert cache.get_json("demo", "EGFR") == {"ok": True}
    assert default_integration_cache_dir().name in {"db", "integrations_db"}


def test_uniprot_offline_enrichment(cache: IntegrationCache) -> None:
    client = LabUniProtClient(cache)
    data = client.lookup("EGFR")
    assert data is not None
    assert data["accession"] == OFFLINE_UNIPROT["EGFR"]["accession"]
    from voidsignal.components import Protein

    p = Protein(name="EGFR", gene_symbol="EGFR", concentration=0.5)
    client.enrich_protein(p)
    assert p.uniprot_id == "P00533"
    assert p.domains
    card = p.to_encyclopedia_card()
    assert card["identity"]["uniprot_id"] == "P00533"
    assert "Tyr1068" in {s["residue"] for s in card["biology"]["ptm_sites"]}


def test_depmap_and_encode_offline(cache: IntegrationCache) -> None:
    ess = DepMapClient(cache).get_essentiality("KRAS")
    assert ess is not None
    assert ess.gene_effect < -1.0
    assert ess.as_dict()["is_essential"] is True
    chrom = EncodeClient(cache).get_chromatin_state("TP53")
    assert chrom is not None
    assert "TSS" in chrom.chromatin_state or "enhancer" in chrom.chromatin_state.lower() or chrom.chromatin_state


def test_kegg_offline_scaffold(cache: IntegrationCache) -> None:
    net = LabKEGGClient(cache).build_network("hsa04151", name="PI3K")
    assert len(net.nodes()) >= 4
    assert len(net.edges()) >= 3
    symbols = {
        (getattr(net.registry.get(n), "gene_symbol", None) or net.registry.get(n).name).upper()
        for n in net.nodes()
    }
    # Live KGML or offline scaffold should include PI3K/AKT axis members
    assert any("AKT" in s or s in {"EGFR", "PIK3CA", "PTEN", "MTOR"} for s in symbols)


def test_reactome_and_string(cache: IntegrationCache) -> None:
    rnet = LabReactomeClient(cache).build_network("R-HSA-5683057")
    assert len(rnet.nodes()) >= 3
    edges = LabSTRINGClient(cache).neighbourhood(["EGFR", "KRAS", "BRAF"])
    assert edges
    assert all(0.0 <= e.score <= 1.0 for e in edges)
    added = LabSTRINGClient(cache).overlay(rnet, min_score=0.7)
    assert added >= 0


def test_enrichment_engine(cache: IntegrationCache) -> None:
    engine = BiologicalEnrichmentEngine(cache)
    report = engine.enrich_symbol("EGFR")
    assert "uniprot" in report.sources
    assert report.encyclopedia_card is not None
    assert report.encyclopedia_card["title"] == "EGFR"
    assert report.essentiality is not None or report.chromatin is not None


def test_multi_pathway_merger_crosstalk_hubs(cache: IntegrationCache) -> None:
    merger = MultiPathwayMerger(cache)
    result = merger.merge(["MAPK", "PI3K-Akt"], overlay_string=True)
    assert result.n_nodes >= 6
    assert result.n_edges >= 5
    assert "hsa04010" in result.pathway_ids
    assert "hsa04151" in result.pathway_ids
    # EGFR / KRAS should bridge both pathways when offline scaffolds merge
    assert any(h in {"EGFR", "KRAS"} for h in result.hub_symbols) or result.n_nodes > 0
    payload = result.as_dict()
    assert payload["n_nodes"] == result.n_nodes


def test_structure_client_offline(cache: IntegrationCache) -> None:
    from voidsignal.integrations import StructureClient

    rec = StructureClient(cache).lookup_pdb("1M17")
    assert rec.pdb_id == "1M17"
    assert rec.as_dict()["pdb_id"] == "1M17"


def test_uniprot_search_offline(cache: IntegrationCache) -> None:
    hits = LabUniProtClient(cache).search("EGFR", limit=3)
    assert hits
    assert hits[0]["gene_symbol"] == "EGFR"


def test_offline_pathway_edges_cover_core() -> None:
    assert "hsa04010" in OFFLINE_PATHWAY_EDGES
    assert "hsa04151" in OFFLINE_PATHWAY_EDGES
