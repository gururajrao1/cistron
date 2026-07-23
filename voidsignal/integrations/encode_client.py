"""ENCODE chromatin-state client (offline-first)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from voidsignal.integrations.cache_store import IntegrationCache
from voidsignal.integrations.offline_data import OFFLINE_ENCODE


@dataclass(frozen=True)
class ChromatinState:
    gene_symbol: str
    chromatin_state: str
    cell_type: str
    assay: str = "ChromHMM"
    source: str = "ENCODE-offline"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "gene_symbol": self.gene_symbol,
            "chromatin_state": self.chromatin_state,
            "cell_type": self.cell_type,
            "assay": self.assay,
            "source": self.source,
        }


class EncodeClient:
    """Promoter / enhancer chromatin priors for lab enrichment cards."""

    def __init__(self, cache: Optional[IntegrationCache] = None) -> None:
        self.cache = cache or IntegrationCache()

    def get_chromatin_state(self, gene_symbol: str) -> Optional[ChromatinState]:
        sym = gene_symbol.strip().upper()
        cached = self.cache.get_json("encode", sym)
        raw = cached if isinstance(cached, dict) else OFFLINE_ENCODE.get(sym)
        if raw is None:
            raw = OFFLINE_ENCODE.get(gene_symbol.strip())
        if raw is None:
            return None
        if cached is None:
            self.cache.set_json("encode", sym, raw)
        return ChromatinState(
            gene_symbol=sym,
            chromatin_state=str(raw["chromatin_state"]),
            cell_type=str(raw.get("cell_type", "unknown")),
            assay=str(raw.get("assay", "ChromHMM")),
            source=str(raw.get("source", "ENCODE-offline")),
        )
