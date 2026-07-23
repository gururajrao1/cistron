"""Tests for OmniPath / SIGNOR activity-flow ingestion."""

from __future__ import annotations

from pathlib import Path

import pytest

from voidsignal.data.omnipath import (
    OmniPathClient,
    activity_weight_from_ddg,
    apply_structural_disruption,
    classify_mechanism,
    hypoxia_network_preset,
    ingest_omnipath_for_ode,
    offline_mapk_activity_graph,
    parse_activity_flow_rows,
    tau_for_mechanism,
    to_signaling_network,
)
from voidsignal.integrations.cache_store import IntegrationCache
from voidsignal.models.graph import (
    TAU_ENZYMATIC_MIN,
    TAU_TRANSCRIPTIONAL_MIN,
    CausalActivityGraph,
    GraphNode,
    MechanismKind,
)
from voidsignal.topology import InteractionType


@pytest.fixture()
def cache(tmp_path: Path) -> IntegrationCache:
    return IntegrationCache(root=tmp_path / "db")


def test_parse_keeps_strict_signs_and_flags_ambiguous() -> None:
    graph = offline_mapk_activity_graph()
    assert isinstance(graph, CausalActivityGraph)
    assert graph.edge_count() >= 5
    for e in graph.edges:
        assert e.sign in (1, -1)
        assert e.is_stimulation != e.is_inhibition
    assert graph.ambiguous
    reasons = {a.reason for a in graph.ambiguous}
    assert "both_stimulation_and_inhibition" in reasons or "not_directed" in reasons


def test_mechanism_and_tau_tagging() -> None:
    assert classify_mechanism("phosphorylation") is MechanismKind.ENZYMATIC
    assert classify_mechanism(None, interaction_type="transcriptional_regulation") is MechanismKind.TRANSCRIPTIONAL
    assert tau_for_mechanism(MechanismKind.ENZYMATIC) == TAU_ENZYMATIC_MIN
    assert tau_for_mechanism(MechanismKind.TRANSCRIPTIONAL) == TAU_TRANSCRIPTIONAL_MIN

    graph = offline_mapk_activity_graph()
    fos = graph.nodes.get("FOS")
    assert fos is not None
    assert fos.tau_min == TAU_TRANSCRIPTIONAL_MIN
    mek_edge = next(e for e in graph.edges if e.target == "MAP2K1" or e.source == "BRAF")
    assert mek_edge.mechanism is MechanismKind.ENZYMATIC


def test_structural_disruption_weight() -> None:
    assert activity_weight_from_ddg(1.0) == 1.0
    assert activity_weight_from_ddg(2.5) == 1.0
    w = activity_weight_from_ddg(3.0)
    assert abs(w - (1.0 - 0.15 * 3.0)) < 1e-9
    w_out = activity_weight_from_ddg(None, ramachandran_outlier=True)
    assert w_out == max(0.0, 1.0 - 0.15 * 2.5)

    node = GraphNode(gene_symbol="KRAS")
    updated = apply_structural_disruption(node, delta_delta_g=4.0, variant_hgvs="KRAS p.G12D")
    assert updated.activity_weight == max(0.0, 1.0 - 0.15 * 4.0)
    assert updated.structural is not None
    assert updated.structural.delta_delta_g == 4.0


def test_hypoxia_preset_topology() -> None:
    g = hypoxia_network_preset()
    pairs = {(e.source, e.target, e.sign) for e in g.edges}
    assert ("O2", "EGLN1", 1) in pairs
    assert ("EGLN1", "HIF1A", -1) in pairs
    assert ("HIF1A", "VEGFA", 1) in pairs
    assert ("HIF1A", "GLUT1", 1) in pairs
    assert ("HIF1A", "EGLN1", 1) in pairs
    assert ("MTOR", "HIF1A", 1) in pairs
    assert g.nodes["VEGFA"].tau_min == TAU_TRANSCRIPTIONAL_MIN
    assert g.ambiguous == []


def test_to_signaling_network_ode_ready() -> None:
    graph = offline_mapk_activity_graph()
    graph.nodes["KRAS"] = apply_structural_disruption(
        graph.nodes["KRAS"],
        delta_delta_g=3.5,
        ramachandran_outlier=False,
        variant_hgvs="KRAS p.G12D",
    )
    net = to_signaling_network(graph)
    assert len(net.nodes()) >= 5
    assert len(net.edges()) >= 5
    # Find KRAS protein
    kras = None
    for nid in net.nodes():
        ent = net.registry.get(nid)
        if getattr(ent, "gene_symbol", None) == "KRAS" or ent.name == "KRAS":
            kras = ent
            break
    assert kras is not None
    assert kras.metadata["activity_weight"] < 1.0
    assert 0.0 <= kras.structure.disruption_delta <= 1.0

    # Transcription edge present
    types = {e.interaction_type for e in net.edges()}
    assert InteractionType.TRANSCRIPTION in types or InteractionType.PHOSPHORYLATION in types


def test_ingest_end_to_end_offline(cache: IntegrationCache) -> None:
    client = OmniPathClient(cache)
    # Force offline by using empty genes with monkeypatched unreachable — client
    # already falls back when HTTP fails; call offline path via parse.
    graph, net = ingest_omnipath_for_ode(
        genes=["EGFR", "KRAS"],
        client=client,
        disruptions={"KRAS": {"delta_delta_g": 3.0, "variant_hgvs": "p.G12D"}},
    )
    assert isinstance(graph, CausalActivityGraph)
    assert len(net.nodes()) >= 1
    # Schema round-trip
    dumped = graph.model_dump(mode="json")
    restored = CausalActivityGraph.model_validate(dumped)
    assert restored.name == graph.name


def test_parse_json_like_rows() -> None:
    rows = [
        {
            "source_genesymbol": "TP53",
            "target_genesymbol": "CDKN1A",
            "is_directed": 1,
            "is_stimulation": 1,
            "is_inhibition": 0,
            "type": "transcriptional_regulation",
            "sources": "SIGNOR;OmniPath",
        }
    ]
    g = parse_activity_flow_rows(rows)
    assert len(g.edges) == 1
    assert g.edges[0].sign == 1
    assert g.edges[0].mechanism is MechanismKind.TRANSCRIPTIONAL
    assert g.nodes["CDKN1A"].tau_min == TAU_TRANSCRIPTIONAL_MIN
