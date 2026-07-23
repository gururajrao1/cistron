"""Lab-facing STRING PPI overlay — live API with offline neighbourhood fallback."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple
from urllib.parse import urlencode
import logging

from voidsignal.integrations.cache_store import IntegrationCache
from voidsignal.integrations.http_sync import http_get_json
from voidsignal.knowledge_graph import PPIEdge
from voidsignal.topology import InteractionType, SignalingNetwork

logger = logging.getLogger(__name__)

_OFFLINE_PPI: List[Tuple[str, str, float]] = [
    ("EGFR", "KRAS", 0.92),
    ("KRAS", "BRAF", 0.95),
    ("BRAF", "MAP2K1", 0.97),
    ("MAP2K1", "MAPK1", 0.98),
    ("EGFR", "PIK3CA", 0.85),
    ("KRAS", "PIK3CA", 0.88),
    ("PIK3CA", "AKT1", 0.9),
    ("TP53", "MDM2", 0.93),
    ("STAT3", "JAK2", 0.86),
]


class LabSTRINGClient:
    """Return PPI edges for overlay onto an existing signalling network."""

    BASE = "https://string-db.org/api"

    def __init__(self, cache: Optional[IntegrationCache] = None, *, species: int = 9606) -> None:
        self.cache = cache or IntegrationCache()
        self.species = species

    def neighbourhood(self, symbols: Optional[List[str]] = None) -> List[PPIEdge]:
        want = {s.upper() for s in (symbols or [])} if symbols else None
        live = self._live_network(list(want) if want else ["EGFR", "KRAS", "BRAF", "MAP2K1", "MAPK1"])
        if live:
            return [e for e in live if not want or e.protein_a.upper() in want or e.protein_b.upper() in want]

        cached = self.cache.get_json("string_lab", "neighbourhood")
        pairs = cached if isinstance(cached, list) else [
            {"a": a, "b": b, "score": s} for a, b, s in _OFFLINE_PPI
        ]
        if cached is None:
            self.cache.set_json("string_lab", "neighbourhood", pairs)
        edges: List[PPIEdge] = []
        for row in pairs:
            a, b, score = str(row["a"]), str(row["b"]), float(row["score"])
            if want and a.upper() not in want and b.upper() not in want:
                continue
            edges.append(
                PPIEdge(
                    protein_a=a,
                    protein_b=b,
                    score=score,
                    evidence="STRING-offline",
                )
            )
        return edges

    def _live_network(self, identifiers: List[str]) -> List[PPIEdge]:
        if not identifiers:
            return []
        cache_key = ",".join(sorted(s.upper() for s in identifiers))
        cached = self.cache.get_json("string_live", cache_key)
        if isinstance(cached, list):
            return [
                PPIEdge(
                    protein_a=str(r["a"]),
                    protein_b=str(r["b"]),
                    score=float(r["score"]),
                    evidence="STRING-cached",
                )
                for r in cached
            ]

        params = urlencode(
            {
                "identifiers": "%0d".join(identifiers),
                "species": str(self.species),
                "required_score": "400",
                "caller_identity": "voidsignal",
            }
        )
        url = f"{self.BASE}/json/network?{params}"
        payload = http_get_json(url)
        if not isinstance(payload, list):
            return []
        rows = []
        edges: List[PPIEdge] = []
        for row in payload:
            if not isinstance(row, dict):
                continue
            a = str(row.get("preferredName_A") or "")
            b = str(row.get("preferredName_B") or "")
            if not a or not b or a == b:
                continue
            raw = row.get("score")
            try:
                score = float(raw) / 1000.0 if raw is not None else 0.0
            except (TypeError, ValueError):
                score = 0.0
            rows.append({"a": a, "b": b, "score": score})
            edges.append(PPIEdge(protein_a=a, protein_b=b, score=score, evidence="STRING-live"))
        if rows:
            self.cache.set_json("string_live", cache_key, rows)
        return edges

    def overlay(self, network: SignalingNetwork, *, min_score: float = 0.7) -> int:
        """Add high-score PPI as soft binding edges between matching symbols."""
        symbol_to_id: Dict[str, str] = {}
        for nid in network.nodes():
            ent = network.registry.get(nid)
            sym = (getattr(ent, "gene_symbol", None) or ent.name).upper()
            symbol_to_id[sym] = nid
        added = 0
        for edge in self.neighbourhood(list(symbol_to_id)):
            if edge.score < min_score:
                continue
            a = symbol_to_id.get(edge.protein_a.upper())
            b = symbol_to_id.get(edge.protein_b.upper())
            if not a or not b or a == b:
                continue
            if b in network.successors(a):
                continue
            network.connect(a, b, InteractionType.BINDING, weight=float(edge.score), rate_constant=0.5)
            added += 1
        return added
