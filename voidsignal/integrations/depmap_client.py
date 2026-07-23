"""DepMap CRISPR essentiality client (offline-first)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from voidsignal.integrations.cache_store import IntegrationCache
from voidsignal.integrations.offline_data import OFFLINE_DEPMAP


@dataclass(frozen=True)
class EssentialityRecord:
    gene_symbol: str
    gene_effect: float
    """Chronos-like score; more negative ⇒ more essential."""
    dependency_prob: float
    lineage: str = "pan-cancer"
    source: str = "DepMap-offline"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "gene_symbol": self.gene_symbol,
            "gene_effect": self.gene_effect,
            "dependency_prob": self.dependency_prob,
            "lineage": self.lineage,
            "source": self.source,
            "is_essential": self.gene_effect <= -0.5,
        }


class DepMapClient:
    """
    CRISPR / DepMap gene-effect lookup.

    Live DepMap portal downloads are large; this client serves curated offline
    scores and caches any injected payloads for later sessions.
    """

    def __init__(self, cache: Optional[IntegrationCache] = None) -> None:
        self.cache = cache or IntegrationCache()

    def get_essentiality(self, gene_symbol: str) -> Optional[EssentialityRecord]:
        sym = gene_symbol.strip().upper()
        cached = self.cache.get_json("depmap", sym)
        raw = cached if isinstance(cached, dict) else OFFLINE_DEPMAP.get(sym)
        if raw is None:
            # try original case keys
            raw = OFFLINE_DEPMAP.get(gene_symbol.strip())
        if raw is None:
            return None
        if cached is None:
            self.cache.set_json("depmap", sym, raw)
        return EssentialityRecord(
            gene_symbol=sym,
            gene_effect=float(raw["gene_effect"]),
            dependency_prob=float(raw.get("dependency_prob", 0.0)),
            lineage=str(raw.get("lineage", "pan-cancer")),
            source=str(raw.get("source", "DepMap-offline")),
        )

    def batch(self, symbols: List[str]) -> List[EssentialityRecord]:
        out: List[EssentialityRecord] = []
        for s in symbols:
            rec = self.get_essentiality(s)
            if rec is not None:
                out.append(rec)
        return out
