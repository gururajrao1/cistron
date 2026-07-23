"""Studio UI payload tests — encyclopedia + causal wiring helpers (v0.19)."""

from __future__ import annotations

import math

from cistron import __version__
from cistron.agent.causal_reasoner import _pct_change
from cistron.components import ClinicalAnnotation, DrugAssociation, Protein
from cistron.simulation import SimulatorBackend, TrajectoryResult
from cistron.topology import InteractionType, SignalingNetwork
from cistron.ui.studio_cards import (
    build_causal_payload,
    crosstalk_viewport_payload,
    demo_rich_mapk_entities,
    encyclopedia_card_for,
    network_encyclopedia_index,
)


def test_version_ui_wiring() -> None:
    assert __version__ == "0.21.0"


def test_encyclopedia_card_payload() -> None:
    egfr = next(e for e in demo_rich_mapk_entities() if e.name == "EGFR")
    card = encyclopedia_card_for(egfr)
    assert card["card_type"] == "protein"
    assert card["identity"]["uniprot_id"] == "P00533"
    assert card["biology"]["cellular_localization"] == "Plasma Membrane"
    assert any(p.get("residue") == "Tyr1068" for p in card["biology"]["ptm_sites"])
    assert card["drugs"][0]["name"] == "Gefitinib"
    assert card["structure"]["pdb_id"] == "1M17"


def test_encyclopedia_fallback_never_raises() -> None:
    bare = Protein(name="ORPHAN", concentration=0.1)
    card = encyclopedia_card_for(bare)
    assert card["title"]
    assert "identity" in card
    assert isinstance(card["biology"].get("domains", []), list)


def test_causal_pct_handles_nan() -> None:
    assert _pct_change(float("nan"), 1.0) == 0.0
    assert _pct_change(1.0, float("inf")) == 0.0
    assert math.isfinite(_pct_change(0.0, 1.0))


def test_crosstalk_viewport_and_causal_payload() -> None:
    net = SignalingNetwork(name="ui_xtalk")
    ids: dict[str, str] = {}
    for name in ("EGFR", "RAS", "RAF", "MEK", "ERK", "PI3K", "AKT"):
        p = Protein(
            name=name,
            gene_symbol=name,
            concentration=0.5,
            pathway_membership=(
                ["MAPK"] if name in {"RAF", "MEK", "ERK"} else ["MAPK", "PI3K-AKT"]
            ),
        )
        if name == "RAS":
            p.clinical = ClinicalAnnotation(somatic_mutations=["KRAS p.G12D"], oncogene=True)
        if name == "PI3K":
            p.drugs = [DrugAssociation(name="Wortmannin", mechanism="inhibitor", ic50_nM=5.0)]
            p.pathway_membership = ["PI3K-AKT"]
        if name == "AKT":
            p.pathway_membership = ["PI3K-AKT"]
        net.add_node(p)
        ids[name] = p.entity_id

    for a, b in (
        ("EGFR", "RAS"),
        ("RAS", "RAF"),
        ("RAF", "MEK"),
        ("MEK", "ERK"),
        ("EGFR", "PI3K"),
        ("RAS", "PI3K"),
        ("PI3K", "AKT"),
    ):
        net.connect(ids[a], ids[b], InteractionType.ACTIVATION)

    net.auto_annotate_canonical_pathways()
    viewport = crosstalk_viewport_payload(net)
    assert "MAPK" in viewport["pathways"]
    assert viewport["crosstalk_switches"]

    index = network_encyclopedia_index(net)
    assert ids["EGFR"] in index

    control = TrajectoryResult(
        times=[0.0, 1.0],
        concentrations=[
            {k: 0.2 for k in ids.values()},
            {
                ids["ERK"]: 0.4,
                ids["AKT"]: 0.5,
                ids["RAS"]: 0.3,
                ids["MEK"]: 0.3,
                ids["PI3K"]: 0.4,
                ids["EGFR"]: 0.5,
                ids["RAF"]: 0.3,
            },
        ],
        boolean_states=[{}, {}],
        backend=SimulatorBackend.ODE,
    )
    pert = TrajectoryResult(
        times=[0.0, 1.0],
        concentrations=[
            {k: 0.2 for k in ids.values()},
            {
                ids["ERK"]: 0.85,
                ids["AKT"]: 0.05,
                ids["RAS"]: 0.9,
                ids["MEK"]: 0.7,
                ids["PI3K"]: 0.05,
                ids["EGFR"]: 0.5,
                ids["RAF"]: 0.6,
            },
        ],
        boolean_states=[{}, {}],
        backend=SimulatorBackend.ODE,
    )
    for sample in control.concentrations + pert.concentrations:
        for k in ids.values():
            sample.setdefault(k, 0.2)

    causal = build_causal_payload(
        net,
        control,
        pert,
        cascade=["EGFR", "RAS", "RAF", "MEK", "ERK"],
    )
    assert causal["cascade"][0] == "EGFR"
    assert causal["overview_narrative"]
    assert causal["activated"] or causal["inactivated"]
