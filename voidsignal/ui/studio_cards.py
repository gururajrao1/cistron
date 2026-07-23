"""
Studio UI payloads — encyclopedia cards + causal narratives for dashboards.

Bridges rich ``components`` / ``CausalBioReasoner`` outputs into JSON shapes
consumed by Streamlit ``app.py`` and the React Research Studio.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from voidsignal.agent.causal_reasoner import CausalBioReasoner, DeltaSummaryReport
from voidsignal.components import BiologicalEntity, Gene, Protein
from voidsignal.simulation import TrajectoryResult
from voidsignal.topology import SignalingNetwork


def encyclopedia_card_for(entity: BiologicalEntity) -> Dict[str, Any]:
    """Return a UniProt-style card; falls back to a minimal dict for plain entities."""
    try:
        if hasattr(entity, "to_encyclopedia_card"):
            card = entity.to_encyclopedia_card()  # type: ignore[misc]
            if isinstance(card, dict) and card:
                return card
    except Exception:
        pass
    base = entity.to_dict() if hasattr(entity, "to_dict") else {}
    return {
        "card_type": getattr(getattr(entity, "entity_type", None), "name", "protein").lower(),
        "title": getattr(entity, "gene_symbol", None) or getattr(entity, "name", "entity"),
        "subtitle": "Select a biological entity to inspect",
        "identity": {
            "gene_symbol": getattr(entity, "gene_symbol", getattr(entity, "name", None)),
            "full_name": getattr(entity, "full_name", None),
            "uniprot_id": getattr(entity, "uniprot_id", None),
            "kegg_id": getattr(entity, "kegg_id", None),
            "aliases": list(getattr(entity, "aliases", []) or []),
            "species": getattr(entity, "species", "Homo sapiens"),
        },
        "biology": {
            "cellular_localization": getattr(entity, "cellular_localization", None),
            "pathway_membership": list(getattr(entity, "pathway_membership", []) or []),
            "domains": [],
            "ptm_sites": [],
        },
        "clinical": getattr(getattr(entity, "clinical", None), "to_dict", lambda: {})(),
        "drugs": [
            d.to_dict() if hasattr(d, "to_dict") else d
            for d in (getattr(entity, "drugs", None) or [])
        ],
        "structure": getattr(getattr(entity, "structure", None), "to_dict", lambda: {})(),
        "kinetics": base.get("kinetics", {}) if isinstance(base, dict) else {},
        "state": {
            "concentration": float(getattr(entity, "concentration", 0.0) or 0.0),
            "boolean_state": getattr(getattr(entity, "boolean_state", None), "name", "OFF"),
            "entity_id": getattr(entity, "entity_id", ""),
        },
        "entity_id": getattr(entity, "entity_id", ""),
    }


def network_encyclopedia_index(network: SignalingNetwork) -> Dict[str, Dict[str, Any]]:
    """Map entity_id / gene_symbol / name → encyclopedia card."""
    index: Dict[str, Dict[str, Any]] = {}
    for nid in network.nodes():
        entity = network.registry.get(nid)
        card = encyclopedia_card_for(entity)
        index[nid] = card
        for key in (
            entity.name,
            getattr(entity, "gene_symbol", None),
            *(getattr(entity, "aliases", None) or []),
        ):
            if key:
                index[str(key)] = card
    return index


def crosstalk_viewport_payload(network: SignalingNetwork) -> Dict[str, Any]:
    """Hubs / bottlenecks / switches for multi-pathway canvas highlighting."""
    if not network.pathway_names():
        network.auto_annotate_canonical_pathways()
    return {
        "pathways": {name: sorted(network.pathway_nodes(name)) for name in network.pathway_names()},
        "hubs": network.get_hub_nodes(top_k=8),
        "bottlenecks": network.get_bottlenecks(top_k=8),
        "crosstalk_switches": network.detect_crosstalk_switches(),
    }


def build_causal_payload(
    network: SignalingNetwork,
    control: TrajectoryResult,
    perturbed: TrajectoryResult,
    *,
    attributions: Optional[Mapping[str, float]] = None,
    cascade: Optional[Sequence[str]] = None,
    control_label: str = "Control (Healthy)",
    perturbed_label: str = "Perturbed (Mutant/Treated)",
) -> Dict[str, Any]:
    """Serialize ``CausalBioReasoner.delta_summary()`` for the Causal Narrative Panel."""
    reasoner = CausalBioReasoner(
        network,
        control,
        perturbed,
        attributions=attributions,
        control_label=control_label,
        perturbed_label=perturbed_label,
    )
    summary: DeltaSummaryReport = reasoner.delta_summary()
    chain_names: List[str] = list(cascade) if cascade else []
    if not chain_names and summary.activated:
        for step in summary.activated[0].chain:
            if not chain_names:
                chain_names.append(step.source_name)
            if step.target_name not in chain_names:
                chain_names.append(step.target_name)
    if not chain_names:
        # Prefer classic MAPK labels when present
        preferred = ("EGF", "EGFR", "RAS", "RAF", "MEK", "ERK")
        names = {network.registry.get(n).name.upper(): network.registry.get(n).name for n in network.nodes()}
        chain_names = [names[p] for p in preferred if p in names]

    return {
        "control_label": summary.control_label,
        "perturbed_label": summary.perturbed_label,
        "overview_narrative": summary.overview_narrative,
        "cascade": chain_names,
        "activated": [e.as_dict() for e in summary.activated],
        "inactivated": [e.as_dict() for e in summary.inactivated],
        "stable": list(summary.stable),
        "metadata": dict(summary.metadata),
    }


def demo_rich_mapk_entities() -> List[BiologicalEntity]:
    """Factory used by Streamlit / smoke demos for encyclopedia rendering."""
    from voidsignal.components import (
        ClinicalAnnotation,
        DrugAssociation,
        ModificationType,
        ProteinDomain,
        StructuralMetadata,
    )
    from voidsignal.components import KineticParameters

    egfr = Protein(
        name="EGFR",
        gene_symbol="EGFR",
        full_name="Epidermal growth factor receptor",
        uniprot_id="P00533",
        kegg_id="hsa:1956",
        aliases=["ERBB1", "HER1"],
        concentration=1.0,
        is_enzyme=True,
        cellular_localization="Plasma Membrane",
        domains=[ProteinDomain(name="kinase", start=712, end=979, domain_type="kinase")],
        structure=StructuralMetadata(pdb_id="1M17", alphafold_plddt_score=86.5),
        clinical=ClinicalAnnotation(
            diseases=["NSCLC", "glioblastoma"],
            somatic_mutations=["EGFR p.L858R"],
            oncogene=True,
        ),
        drugs=[DrugAssociation(name="Gefitinib", mechanism="inhibitor", ic50_nM=33.0, approval_status="approved")],
        pathway_membership=["MAPK", "PI3K-AKT"],
        kinetics=KineticParameters(vmax=2.0, km=0.5, degradation_rate=0.05),
    )
    egfr.set_modification(
        "Tyr1068",
        ModificationType.PHOSPHORYLATION,
        1.0,
        residue="Tyr1068",
        occupancy=0.85,
        active=True,
    )
    ras = Protein(
        name="RAS",
        gene_symbol="KRAS",
        full_name="GTPase KRas",
        uniprot_id="P01116",
        concentration=0.8,
        cellular_localization="Plasma Membrane",
        clinical=ClinicalAnnotation(somatic_mutations=["KRAS p.G12D"], oncogene=True, diseases=["CRC", "PDAC"]),
        pathway_membership=["MAPK", "PI3K-AKT"],
    )
    mek = Protein(
        name="MEK",
        gene_symbol="MAP2K1",
        full_name="Dual specificity mitogen-activated protein kinase kinase 1",
        uniprot_id="Q02750",
        concentration=0.5,
        cellular_localization="Cytosol",
        drugs=[DrugAssociation(name="Trametinib", mechanism="inhibitor", ic50_nM=0.92, approval_status="approved")],
        pathway_membership=["MAPK"],
    )
    erk = Protein(
        name="ERK",
        gene_symbol="MAPK1",
        full_name="Mitogen-activated protein kinase 1",
        uniprot_id="P28482",
        concentration=0.4,
        cellular_localization="Cytosol / Nucleus",
        pathway_membership=["MAPK"],
    )
    akt = Protein(
        name="AKT",
        gene_symbol="AKT1",
        full_name="RAC-alpha serine/threonine-protein kinase",
        uniprot_id="P31749",
        concentration=0.35,
        cellular_localization="Cytosol",
        pathway_membership=["PI3K-AKT"],
    )
    pi3k = Protein(
        name="PI3K",
        gene_symbol="PIK3CA",
        full_name="Phosphatidylinositol 4,5-bisphosphate 3-kinase catalytic subunit alpha",
        uniprot_id="P42336",
        concentration=0.4,
        cellular_localization="Plasma Membrane",
        drugs=[DrugAssociation(name="Wortmannin", mechanism="inhibitor", ic50_nM=5.0)],
        pathway_membership=["PI3K-AKT"],
    )
    tp53 = Gene(
        name="TP53",
        gene_symbol="TP53",
        full_name="Tumor protein p53",
        uniprot_id="P04637",
        cellular_localization="Nucleus",
        clinical=ClinicalAnnotation(
            somatic_mutations=["TP53 p.R213*"],
            tumor_suppressor=True,
            diseases=["Li-Fraumeni"],
        ),
        pathway_membership=["JAK-STAT"],
    )
    return [egfr, ras, mek, erk, akt, pi3k, tp53]


__all__ = [
    "build_causal_payload",
    "crosstalk_viewport_payload",
    "demo_rich_mapk_entities",
    "encyclopedia_card_for",
    "network_encyclopedia_index",
]
