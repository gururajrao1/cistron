"""Lab-facing KEGG client — live REST KGML with offline scaffolds."""

from __future__ import annotations

from typing import Dict, List, Optional
import logging

from cistron.components import KineticParameters, Protein
from cistron.integrations.cache_store import IntegrationCache
from cistron.integrations.http_sync import http_get_text
from cistron.integrations.offline_data import OFFLINE_PATHWAY_EDGES
from cistron.knowledge_graph import KEGGClient, pathway_map_to_network
from cistron.topology import InteractionType, SignalingNetwork
from cistron.vendored import VendoredPathwayRepository

logger = logging.getLogger(__name__)

_TYPE_MAP = {
    "activation": InteractionType.ACTIVATION,
    "inhibition": InteractionType.INHIBITION,
    "phosphorylation": InteractionType.PHOSPHORYLATION,
    "transcription": InteractionType.TRANSCRIPTION,
}


class LabKEGGClient:
    """
    Build signalling networks from KEGG pathway IDs.

    Strategy: live REST KGML → disk cache → vendored KGML → offline edge scaffolds.
    """

    BASE = "https://rest.kegg.jp"

    def __init__(self, cache: Optional[IntegrationCache] = None) -> None:
        self.cache = cache or IntegrationCache()
        self._vendored = VendoredPathwayRepository()
        self._parser = KEGGClient(cache=self.cache.http)

    def build_network(self, pathway_id: str, *, name: Optional[str] = None) -> SignalingNetwork:
        pid = pathway_id.strip()
        display = name or pid

        # 1) Live (or cached) KGML
        kgml = self._fetch_kgml(pid)
        if kgml:
            try:
                pmap = self._parser.parse_kgml(kgml, pathway_id=pid)
                net = pathway_map_to_network(pmap, default_concentration=0.4)
                net.name = display
                net.annotate_pathway(pid, net.nodes())
                net.auto_annotate_canonical_pathways()
                self.cache.set_json("kegg_lab", pid, {"n_edges": len(net.edges()), "source": "live"})
                return net
            except Exception as exc:
                logger.debug("KEGG live parse failed for %s: %s", pid, exc)

        # 2) Vendored MAPK etc.
        if self._vendored.has(pid):
            try:
                net = self._vendored.load_network(pid)
                net.name = display
                net.auto_annotate_canonical_pathways()
                net.annotate_pathway(pid, net.nodes())
                return net
            except Exception as exc:
                logger.debug("Vendored KEGG load failed for %s: %s", pid, exc)

        # 3) Offline edge scaffolds
        edges = OFFLINE_PATHWAY_EDGES.get(pid) or OFFLINE_PATHWAY_EDGES.get(pid.lower())
        if edges:
            net = self._from_edges(pid, edges, display_name=display)
            self.cache.set_json("kegg_lab", pid, {"n_edges": len(edges), "source": "offline"})
            return net

        net = SignalingNetwork(name=display)
        for sym in ("EGFR", "KRAS", "MAPK1"):
            p = Protein(name=sym, gene_symbol=sym, concentration=0.4, pathway_membership=[pid])
            net.add_node(p)
        net.auto_annotate_canonical_pathways()
        self.cache.set_json("kegg_lab", pid, {"n_edges": 0, "source": "stub"})
        return net

    def _fetch_kgml(self, pathway_id: str) -> Optional[str]:
        cached = self.cache.get_json("kegg_kgml", pathway_id)
        if isinstance(cached, dict) and cached.get("kgml"):
            return str(cached["kgml"])
        url = f"{self.BASE}/get/{pathway_id}/kgml"
        text = http_get_text(
            url,
            timeout=2.0,
            accept="application/xml, text/xml, */*",
        )
        if text and "<pathway" in text:
            self.cache.set_json("kegg_kgml", pathway_id, {"kgml": text})
            return text
        return None

    def _from_edges(
        self,
        pathway_id: str,
        edges: List[Dict[str, str]],
        *,
        display_name: str,
    ) -> SignalingNetwork:
        net = SignalingNetwork(name=display_name)
        ids: Dict[str, str] = {}
        symbols = sorted({e["source"] for e in edges} | {e["target"] for e in edges})
        for sym in symbols:
            p = Protein(
                name=sym,
                gene_symbol=sym,
                concentration=0.45,
                pathway_membership=[pathway_id],
                kinetics=KineticParameters(degradation_rate=0.05, production_rate=0.02),
            )
            net.add_node(p)
            ids[sym] = p.entity_id
        for e in edges:
            itype = _TYPE_MAP.get(e.get("type", "activation"), InteractionType.ACTIVATION)
            net.connect(ids[e["source"]], ids[e["target"]], itype, rate_constant=1.0)
        net.annotate_pathway(pathway_id, net.nodes())
        net.auto_annotate_canonical_pathways()
        return net
