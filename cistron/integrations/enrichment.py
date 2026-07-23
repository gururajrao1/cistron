"""Multi-source biological enrichment engine for Virtual Cellular Laboratory."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from cistron.components import Protein
from cistron.integrations.cache_store import IntegrationCache
from cistron.integrations.depmap_client import DepMapClient, EssentialityRecord
from cistron.integrations.encode_client import ChromatinState, EncodeClient
from cistron.integrations.structure_client import StructureClient, StructureRecord
from cistron.integrations.uniprot_client import LabUniProtClient
from cistron.topology import SignalingNetwork


@dataclass
class EnrichmentReport:
    """Aggregated enrichment for one gene / protein."""

    gene_symbol: str
    uniprot: Optional[Dict[str, Any]] = None
    essentiality: Optional[EssentialityRecord] = None
    chromatin: Optional[ChromatinState] = None
    structure: Optional[StructureRecord] = None
    encyclopedia_card: Optional[Dict[str, Any]] = None
    sources: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "gene_symbol": self.gene_symbol,
            "uniprot": self.uniprot,
            "essentiality": self.essentiality.as_dict() if self.essentiality else None,
            "chromatin": self.chromatin.as_dict() if self.chromatin else None,
            "structure": self.structure.as_dict() if self.structure else None,
            "encyclopedia_card": self.encyclopedia_card,
            "sources": list(self.sources),
        }


class BiologicalEnrichmentEngine:
    """
    Compose UniProt + DepMap + ENCODE + structure annotations onto Protein nodes.

    Offline corpora guarantee enrichment works without network access.
    """

    def __init__(self, cache: Optional[IntegrationCache] = None) -> None:
        self.cache = cache or IntegrationCache()
        self.uniprot = LabUniProtClient(self.cache)
        self.depmap = DepMapClient(self.cache)
        self.encode = EncodeClient(self.cache)
        self.structure = StructureClient(self.cache)

    def enrich_symbol(self, gene_symbol: str) -> EnrichmentReport:
        sym = gene_symbol.strip().upper()
        sources: List[str] = []
        uni = self.uniprot.lookup(sym)
        if uni:
            sources.append("uniprot")
        ess = self.depmap.get_essentiality(sym)
        if ess:
            sources.append("depmap")
        chrom = self.encode.get_chromatin_state(sym)
        if chrom:
            sources.append("encode")
        struct = None
        pdb_ids = (uni or {}).get("pdb_ids") or []
        accession = (uni or {}).get("accession")
        if pdb_ids or accession:
            struct = self.structure.enrich_from_uniprot_or_pdb(
                pdb_id=str(pdb_ids[0]) if pdb_ids else None,
                uniprot_id=str(accession) if accession else None,
            )
            if struct and struct.source != "empty":
                sources.append("structure")

        protein = Protein(name=sym, gene_symbol=sym, concentration=0.4)
        if uni:
            self.uniprot.enrich_protein(protein)
        if struct and struct.mean_plddt is not None and protein.structure.alphafold_plddt_score is None:
            from cistron.components import StructuralMetadata

            protein.structure = StructuralMetadata(
                pdb_id=struct.pdb_id or protein.structure.pdb_id,
                alphafold_plddt_score=struct.mean_plddt,
                active_site_center=struct.active_site_center,
                active_site_size=struct.active_site_size,
                disruption_delta=protein.structure.disruption_delta,
            )
        if ess:
            protein.metadata["depmap_gene_effect"] = ess.gene_effect
            protein.metadata["depmap_dependency_prob"] = ess.dependency_prob
            protein.metadata["is_essential"] = ess.gene_effect <= -0.5
        if chrom:
            protein.metadata["chromatin_state"] = chrom.chromatin_state
            protein.metadata["encode_cell_type"] = chrom.cell_type

        card = protein.to_encyclopedia_card()
        card["enrichment"] = {
            "essentiality": ess.as_dict() if ess else None,
            "chromatin": chrom.as_dict() if chrom else None,
            "structure": struct.as_dict() if struct else None,
        }
        return EnrichmentReport(
            gene_symbol=sym,
            uniprot=uni,
            essentiality=ess,
            chromatin=chrom,
            structure=struct,
            encyclopedia_card=card,
            sources=sources,
        )

    def enrich_network(self, network: SignalingNetwork) -> Dict[str, EnrichmentReport]:
        """Enrich every Protein node; return symbol → report map."""
        reports: Dict[str, EnrichmentReport] = {}
        for nid in network.nodes():
            entity = network.registry.get(nid)
            if not isinstance(entity, Protein):
                continue
            sym = (entity.gene_symbol or entity.name).upper()
            report = self.enrich_symbol(sym)
            self.uniprot.enrich_protein(entity)
            if report.essentiality:
                entity.metadata["depmap_gene_effect"] = report.essentiality.gene_effect
                entity.metadata["is_essential"] = report.essentiality.gene_effect <= -0.5
            if report.chromatin:
                entity.metadata["chromatin_state"] = report.chromatin.chromatin_state
            reports[sym] = report
        return reports
