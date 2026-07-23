"""Multi-pathway crosstalk merger — unite KEGG/Reactome graphs on shared hubs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set

from voidsignal.components import Protein
from voidsignal.integrations.cache_store import IntegrationCache
from voidsignal.integrations.catalog import PathwayCatalogEntry, resolve_pathway_ids
from voidsignal.integrations.kegg_client import LabKEGGClient
from voidsignal.integrations.reactome_client import LabReactomeClient
from voidsignal.integrations.string_client import LabSTRINGClient
from voidsignal.topology import InteractionType, SignalingNetwork


@dataclass
class MergeResult:
    """Outcome of merging one or more pathway selectors into a single network."""

    network: SignalingNetwork
    pathway_ids: List[str]
    hub_symbols: List[str]
    n_nodes: int
    n_edges: int
    string_edges_added: int = 0
    notes: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, object]:
        return {
            "pathway_ids": list(self.pathway_ids),
            "hub_symbols": list(self.hub_symbols),
            "n_nodes": self.n_nodes,
            "n_edges": self.n_edges,
            "string_edges_added": self.string_edges_added,
            "notes": list(self.notes),
            "name": self.network.name,
        }


class MultiPathwayMerger:
    """
    Dynamically merge pathway graphs on shared gene-symbol hubs.

    Example::

        merger = MultiPathwayMerger()
        result = merger.merge(["MAPK", "PI3K-Akt"])
        # EGFR / KRAS become crosstalk switches connecting both cascades
    """

    def __init__(self, cache: Optional[IntegrationCache] = None) -> None:
        self.cache = cache or IntegrationCache()
        self.kegg = LabKEGGClient(self.cache)
        self.reactome = LabReactomeClient(self.cache)
        self.string = LabSTRINGClient(self.cache)

    def load_pathway(self, entry: PathwayCatalogEntry) -> SignalingNetwork:
        if entry.source == "reactome" or (
            entry.pathway_id.startswith("R-HSA") and entry.source != "kegg"
        ):
            return self.reactome.build_network(entry.pathway_id, name=entry.name)
        pid = entry.kegg_id or entry.pathway_id
        if pid.startswith("domain:"):
            # Domain stubs: chain hub genes
            net = SignalingNetwork(name=entry.name)
            ids = {}
            for g in entry.hub_genes or ("EGFR", "KRAS"):
                p = Protein(
                    name=g,
                    gene_symbol=g,
                    concentration=0.4,
                    pathway_membership=[entry.pathway_id],
                )
                net.add_node(p)
                ids[g] = p.entity_id
            hubs = list(entry.hub_genes)
            for a, b in zip(hubs, hubs[1:]):
                net.connect(ids[a], ids[b], InteractionType.ACTIVATION, rate_constant=1.0)
            net.annotate_pathway(entry.pathway_id, net.nodes())
            return net
        return self.kegg.build_network(pid, name=entry.name)

    def merge(
        self,
        selectors: Sequence[str],
        *,
        name: Optional[str] = None,
        overlay_string: bool = True,
        min_string_score: float = 0.7,
    ) -> MergeResult:
        entries = resolve_pathway_ids(list(selectors))
        notes: List[str] = []
        if not entries:
            # Fall back to MAPK + PI3K when selectors are unknown
            entries = resolve_pathway_ids(["hsa04010", "hsa04151"])
            notes.append("unknown selectors; defaulted to MAPK + PI3K-Akt")

        graphs = [self.load_pathway(e) for e in entries]
        merged = self._union(graphs, pathway_labels=[e.pathway_id for e in entries])
        display = name or " + ".join(e.name.split()[0] for e in entries)
        merged.name = display

        hubs = self._shared_hubs(merged, [e.pathway_id for e in entries])
        string_added = 0
        if overlay_string:
            string_added = self.string.overlay(merged, min_score=min_string_score)
            if string_added:
                notes.append(f"STRING overlay added {string_added} edges")

        merged.auto_annotate_canonical_pathways()
        for e in entries:
            # Re-annotate membership for UI crosstalk highlighters
            member_ids = [
                nid
                for nid in merged.nodes()
                if e.pathway_id in merged.node_pathways(nid)
                or (getattr(merged.registry.get(nid), "gene_symbol", "") or "").upper()
                in {g.upper() for g in e.hub_genes}
            ]
            if member_ids:
                merged.annotate_pathway(e.pathway_id, member_ids)

        return MergeResult(
            network=merged,
            pathway_ids=[e.pathway_id for e in entries],
            hub_symbols=hubs,
            n_nodes=len(merged.nodes()),
            n_edges=len(merged.edges()),
            string_edges_added=string_added,
            notes=notes,
        )

    def _union(
        self,
        graphs: Sequence[SignalingNetwork],
        *,
        pathway_labels: Sequence[str],
    ) -> SignalingNetwork:
        out = SignalingNetwork(name="merged")
        # Map gene_symbol → entity_id in the merged graph
        symbol_to_id: Dict[str, str] = {}

        for graph, label in zip(graphs, pathway_labels):
            local_map: Dict[str, str] = {}  # old id → new id
            for nid in graph.nodes():
                ent = graph.registry.get(nid)
                sym = (getattr(ent, "gene_symbol", None) or ent.name).upper()
                if sym in symbol_to_id:
                    # Shared hub — keep existing node, extend membership
                    existing_id = symbol_to_id[sym]
                    existing = out.registry.get(existing_id)
                    membership = list(getattr(existing, "pathway_membership", []) or [])
                    if label not in membership:
                        membership.append(label)
                    if hasattr(existing, "pathway_membership"):
                        existing.pathway_membership = membership
                    local_map[nid] = existing_id
                else:
                    # Clone a lightweight Protein so IDs stay unique per merge
                    if isinstance(ent, Protein):
                        clone = Protein(
                            name=ent.name,
                            gene_symbol=ent.gene_symbol or ent.name,
                            concentration=float(ent.concentration),
                            pathway_membership=list(
                                getattr(ent, "pathway_membership", None) or [label]
                            ),
                            kinetics=ent.kinetics,
                        )
                        if label not in clone.pathway_membership:
                            clone.pathway_membership.append(label)
                    else:
                        clone = Protein(
                            name=ent.name,
                            gene_symbol=ent.name,
                            concentration=0.4,
                            pathway_membership=[label],
                        )
                    new_id = out.add_node(clone)
                    symbol_to_id[sym] = new_id
                    local_map[nid] = new_id

            for edge in graph.edges():
                src = local_map.get(edge.source_id)
                tgt = local_map.get(edge.target_id)
                if not src or not tgt or src == tgt:
                    continue
                if tgt in out.successors(src):
                    continue
                out.connect(
                    src,
                    tgt,
                    edge.interaction_type,
                    weight=edge.weight,
                    rate_constant=edge.rate_constant,
                )

        return out

    @staticmethod
    def _shared_hubs(network: SignalingNetwork, pathway_ids: Iterable[str]) -> List[str]:
        want = set(pathway_ids)
        hubs: List[str] = []
        seen: Set[str] = set()
        for nid in network.nodes():
            paths = network.node_pathways(nid)
            if len(paths.intersection(want)) >= 2:
                ent = network.registry.get(nid)
                sym = (getattr(ent, "gene_symbol", None) or ent.name).upper()
                if sym not in seen:
                    seen.add(sym)
                    hubs.append(sym)
        # Prefer canonical oncogene order
        priority = ["EGFR", "KRAS", "TP53", "PIK3CA", "AKT1", "MAPK1"]
        hubs.sort(key=lambda s: (priority.index(s) if s in priority else 99, s))
        return hubs
