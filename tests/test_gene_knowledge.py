"""Retrieve-grounded protein cards for arbitrary symbols."""

from __future__ import annotations

from fastapi.testclient import TestClient

from cistron.api.app import create_app
from cistron.api.gene_knowledge import resolve_gene_knowledge
from cistron.api.protein_explainer import build_protein_card


def test_resolve_o2_clamp() -> None:
    k = resolve_gene_knowledge("O2")
    assert k["gene_symbol"] == "O2"
    assert "model_clamp" in k["sources_used"]
    assert k["summary"]


def test_build_card_from_mygene_shaped_facts() -> None:
    meta = {
        "gene_symbol": "CDK2",
        "uniprot_id": "P24941",
        "accession": "P24941",
        "full_name": "Cyclin-dependent kinase 2",
        "localization": "Nucleus",
        "function": "Serine/threonine-protein kinase involved in cell cycle.",
        "summary": "CDK2 is a catalytic subunit of the cyclin-dependent kinase complex.",
        "diseases": [],
        "entrezgene": "1017",
        "type_of_gene": "protein-coding",
        "sources_used": ["mygene", "uniprot"],
        "alphafold_url": "https://alphafold.ebi.ac.uk/entry/P24941",
    }
    card = build_protein_card(
        "CDK2",
        meta,
        condition_query="Colorectal Cancer",
        upstream=["CCNE1"],
        downstream=["RB1"],
        use_llm=False,
    )
    assert card["gene_symbol"] == "CDK2"
    assert "CDK2" in card["plain_english"]
    assert "Colorectal" in card["why_it_matters"] or "experiment" in card["why_it_matters"].lower()
    assert "CCNE1" in card["in_this_network"]
    assert card["narrative_mode"] in {"template", "template_curated"}
    assert "mygene" in card["sources_used"]
    assert card["entrez_url"]
    impact = card["disease_impact"]
    assert impact["overview"]
    assert "Colorectal" in impact["overview"] or "Colorectal" in impact["if_activity_up"]
    assert "RB1" in impact["if_activity_up"] or "CCNE1" in impact["if_activity_down"]
    assert impact["mode"] == "template"


def test_proteins_endpoint_arbitrary_symbol() -> None:
    with TestClient(create_app()) as client:
        r = client.get(
            "/api/v1/proteins/CDK2",
            params={
                "condition": "Cell cycle",
                "upstream": "CCNE1",
                "use_llm": "false",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["gene_symbol"] == "CDK2"
        assert body["plain_english"]
        assert body["narrative_mode"]
        assert isinstance(body["sources_used"], list)
        assert body.get("disease_impact", {}).get("overview")
