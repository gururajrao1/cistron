"""Disk cache root for Virtual Cellular Laboratory integrations."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Union
import json
import time

from cistron.cache import ResponseCache, default_cache_path, make_cache_key

PathLike = Union[str, Path]


def default_integration_cache_dir() -> Path:
    """Prefer ``.cache/cistron/db``; fall back beside the HTTP SQLite cache."""
    preferred = Path(".cache") / "cistron" / "db"
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        return preferred
    except OSError:
        root = default_cache_path().parent
        alt = root / "integrations_db"
        alt.mkdir(parents=True, exist_ok=True)
        return alt


class IntegrationCache:
    """
    Namespaced JSON document store on top of :class:`ResponseCache`.

    Used by DepMap / ENCODE / UniProt enrichment so offline demos stay fast.
    """

    def __init__(self, root: Optional[PathLike] = None, *, ttl: float = 7 * 86_400.0) -> None:
        root_path = Path(root) if root is not None else default_integration_cache_dir()
        root_path.mkdir(parents=True, exist_ok=True)
        self.root = root_path
        self.ttl = float(ttl)
        self._http = ResponseCache(path=root_path / "integrations_http.sqlite3", default_ttl=ttl)

    @property
    def http(self) -> ResponseCache:
        return self._http

    def get_json(self, namespace: str, key: str) -> Optional[Any]:
        entry = self._http.get(namespace, make_cache_key(key))
        if entry is None:
            return None
        return entry.payload

    def set_json(self, namespace: str, key: str, payload: Any, *, ttl: Optional[float] = None) -> None:
        self._http.set(namespace, make_cache_key(key), payload, ttl=ttl or self.ttl)

    def write_sidecar(self, name: str, payload: Any) -> Path:
        """Write a human-inspectable JSON sidecar next to the SQLite store."""
        path = self.root / f"{name}.json"
        path.write_text(json.dumps({"saved_at": time.time(), "payload": payload}, indent=2), encoding="utf-8")
        return path
