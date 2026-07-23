"""Lab-facing Reactome client (offline participant lists)."""

from __future__ import annotations

from typing import Dict, List, Optional

from cistron.components import Protein
from cistron.integrations.cache_store import IntegrationCache
from cistron.integrations.catalog import resolve_pathway_ids
from cistron.topology import InteractionType, SignalingNetwork


# Curated Reactome-ish participant sets for offline demos
_REACTOME_PARTICIPANTS: Dict[str, List[str]] = {
    "R-HSA-5683057": ["EGFR", "KRAS", "BRAF", "MAP2K1", "MAPK1"],
    "R-HSA-2219528": ["EGFR", "PIK3CA", "AKT1", "MTOR", "PTEN"],
}


class LabReactomeClient:
    """Resolve Reactome pathway IDs to lightweight signalling scaffolds."""

    def __init__(self, cache: Optional[IntegrationCache] = None) -> None:
        self.cache = cache or IntegrationCache()

    def participants(self, reactome_id: str) -> List[str]:
        rid = reactome_id.strip()
        cached = self.cache.get_json("reactome_lab", rid)
        if isinstance(cached, dict) and "participants" in cached:
            return list(cached["participants"])
        # Catalog hub genes as fallback
        entries = resolve_pathway_ids([rid])
        if entries and entries[0].hub_genes:
            genes = list(entries[0].hub_genes)
        else:
            genes = list(_REACTOME_PARTICIPANTS.get(rid, ["TP53", "MDM2"]))
        self.cache.set_json("reactome_lab", rid, {"participants": genes})
        return genes

    def build_network(self, reactome_id: str, *, name: Optional[str] = None) -> SignalingNetwork:
        genes = self.participants(reactome_id)
        net = SignalingNetwork(name=name or reactome_id)
        ids = {}
        for g in genes:
            p = Protein(name=g, gene_symbol=g, concentration=0.4, pathway_membership=[reactome_id])
            net.add_node(p)
            ids[g] = p.entity_id
        # Chain participants as activation cascade for lab demos
        for a, b in zip(genes, genes[1:]):
            net.connect(ids[a], ids[b], InteractionType.ACTIVATION, rate_constant=1.0)
        net.annotate_pathway(reactome_id, net.nodes())
        net.auto_annotate_canonical_pathways()
        return net
