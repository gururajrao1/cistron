"""
Pre-compiled local graph caches for circuit-breaker fallbacks.

When external knowledge APIs time out or fail, the resolver drops back to
these curated scaffolds so Studio / search-and-simulate stay interactive.
"""

from __future__ import annotations

from typing import Optional

from cistron.data.omnipath import (
    hypoxia_network_preset,
    offline_mapk_activity_graph,
)
from cistron.models.graph import CausalActivityGraph


def local_graph_cache(
    profile_id: str = "hypoxia",
    *,
    query: str = "",
) -> CausalActivityGraph:
    """
    Return the pre-compiled local topology for a condition profile.

    Prefer hypoxia / MAPK canonical presets; unknown profiles fall back to
    hypoxia so callers always receive a simulate-ready graph.
    """
    pid = (profile_id or "").strip().lower()
    q = (query or "").lower()

    if pid in {"mapk", "egfr", "glioblastoma", "tnbc"} or any(
        tok in q for tok in ("egfr", "mapk", "ras", "raf", "mek")
    ):
        graph = offline_mapk_activity_graph()
        graph.provenance = {
            **(graph.provenance or {}),
            "fallback": "presets.local_graph_cache",
            "profile_id": pid or "mapk",
        }
        return graph

    graph = hypoxia_network_preset()
    graph.provenance = {
        **(graph.provenance or {}),
        "fallback": "presets.local_graph_cache",
        "profile_id": pid or "hypoxia",
    }
    return graph


def hypoxia_preset() -> CausalActivityGraph:
    """Canonical hypoxia scaffold (alias for callers expecting presets API)."""
    return local_graph_cache("hypoxia")


def mapk_preset() -> CausalActivityGraph:
    """Canonical MAPK scaffold."""
    return local_graph_cache("mapk")


__all__ = [
    "hypoxia_preset",
    "local_graph_cache",
    "mapk_preset",
]
