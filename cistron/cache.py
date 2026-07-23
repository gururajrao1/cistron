"""
Persistent local HTTP response cache for CISTRON Phase 2.

Thread-safe SQLite store used by UniProt / KEGG / STRING (and other) clients
to avoid redundant network round-trips and absorb rate-limit pressure.

Schema
------
``responses(namespace, cache_key, payload_json, content_type, status,
            created_at, expires_at)`` with a composite primary key on
``(namespace, cache_key)``.

TTL is dynamic: callers may override per write; expired rows are ignored on
read and lazily purged.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Union
import json
import logging
import sqlite3
import threading
import time

logger = logging.getLogger(__name__)

PathLike = Union[str, Path]

_DEFAULT_DB_NAME = "cistron_http_cache.sqlite3"


@dataclass(frozen=True)
class CacheEntry:
    """A single cached payload with provenance timestamps."""

    namespace: str
    cache_key: str
    payload: Any
    content_type: str
    status: int
    created_at: float
    expires_at: float

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at

    @property
    def ttl_remaining(self) -> float:
        return max(0.0, self.expires_at - time.time())


class ResponseCache:
    """
    Thread-safe SQLite response cache.

    Parameters
    ----------
    path :
        Database file path. Parent directories are created automatically.
        Pass ``":memory:"`` for ephemeral unit tests.
    default_ttl :
        Seconds a write lives when the caller does not specify ``ttl``.
    purge_on_start :
        If True, drop already-expired rows during ``__init__``.
    """

    def __init__(
        self,
        path: Optional[PathLike] = None,
        *,
        default_ttl: float = 86_400.0,
        purge_on_start: bool = True,
    ) -> None:
        if path is None:
            path = default_cache_path()
        if default_ttl <= 0.0:
            raise ValueError("default_ttl must be positive")
        self.path: Union[str, Path] = path if path == ":memory:" else Path(path)
        self.default_ttl = float(default_ttl)
        self._lock = threading.RLock()
        self._memory = self.path == ":memory:"
        if not self._memory:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = self._connect()
        self._init_schema()
        if purge_on_start:
            self.purge_expired()

    def _connect(self) -> sqlite3.Connection:
        uri = ":memory:" if self._memory else str(self.path)
        conn = sqlite3.connect(uri, check_same_thread=False, isolation_level=None)
        conn.row_factory = sqlite3.Row
        with self._lock:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA temp_store=MEMORY;")
        return conn

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS responses (
                    namespace     TEXT NOT NULL,
                    cache_key    TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    content_type TEXT NOT NULL DEFAULT 'application/json',
                    status       INTEGER NOT NULL DEFAULT 200,
                    created_at   REAL NOT NULL,
                    expires_at   REAL NOT NULL,
                    PRIMARY KEY (namespace, cache_key)
                )
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_responses_expires
                ON responses (expires_at)
                """
            )

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.Error as exc:
                logger.warning("Cache close error: %s", exc)

    def __enter__(self) -> "ResponseCache":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -- core API -----------------------------------------------------------

    def get(self, namespace: str, cache_key: str) -> Optional[CacheEntry]:
        """
        Return a live cache entry or ``None`` on miss / expiry.

        Expired rows are deleted opportunistically.
        """
        if not namespace or not cache_key:
            raise ValueError("namespace and cache_key are required")
        now = time.time()
        with self._lock:
            row = self._conn.execute(
                """
                SELECT namespace, cache_key, payload_json, content_type, status,
                       created_at, expires_at
                FROM responses
                WHERE namespace = ? AND cache_key = ?
                """,
                (namespace, cache_key),
            ).fetchone()
            if row is None:
                return None
            if float(row["expires_at"]) <= now:
                self._conn.execute(
                    "DELETE FROM responses WHERE namespace = ? AND cache_key = ?",
                    (namespace, cache_key),
                )
                logger.debug("Cache expired %s/%s", namespace, cache_key)
                return None
            try:
                payload = json.loads(row["payload_json"])
            except json.JSONDecodeError as exc:
                logger.error("Corrupt cache payload for %s/%s: %s", namespace, cache_key, exc)
                self._conn.execute(
                    "DELETE FROM responses WHERE namespace = ? AND cache_key = ?",
                    (namespace, cache_key),
                )
                return None
            return CacheEntry(
                namespace=row["namespace"],
                cache_key=row["cache_key"],
                payload=payload,
                content_type=row["content_type"],
                status=int(row["status"]),
                created_at=float(row["created_at"]),
                expires_at=float(row["expires_at"]),
            )

    def set(
        self,
        namespace: str,
        cache_key: str,
        payload: Any,
        *,
        ttl: Optional[float] = None,
        content_type: str = "application/json",
        status: int = 200,
    ) -> CacheEntry:
        """Upsert a JSON-serialisable payload with a TTL."""
        if not namespace or not cache_key:
            raise ValueError("namespace and cache_key are required")
        lifetime = float(ttl) if ttl is not None else self.default_ttl
        if lifetime <= 0.0:
            raise ValueError("ttl must be positive")
        try:
            blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"payload is not JSON-serialisable: {exc}") from exc
        now = time.time()
        expires = now + lifetime
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO responses (
                    namespace, cache_key, payload_json, content_type, status,
                    created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(namespace, cache_key) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    content_type = excluded.content_type,
                    status = excluded.status,
                    created_at = excluded.created_at,
                    expires_at = excluded.expires_at
                """,
                (namespace, cache_key, blob, content_type, int(status), now, expires),
            )
        logger.debug("Cache store %s/%s ttl=%.0fs", namespace, cache_key, lifetime)
        return CacheEntry(
            namespace=namespace,
            cache_key=cache_key,
            payload=payload,
            content_type=content_type,
            status=int(status),
            created_at=now,
            expires_at=expires,
        )

    def delete(self, namespace: str, cache_key: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM responses WHERE namespace = ? AND cache_key = ?",
                (namespace, cache_key),
            )
            return cur.rowcount > 0

    def clear_namespace(self, namespace: str) -> int:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM responses WHERE namespace = ?",
                (namespace,),
            )
            return int(cur.rowcount)

    def purge_expired(self) -> int:
        now = time.time()
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM responses WHERE expires_at <= ?",
                (now,),
            )
            removed = int(cur.rowcount)
        if removed:
            logger.info("Purged %d expired cache rows", removed)
        return removed

    def stats(self) -> Dict[str, Any]:
        now = time.time()
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) AS n FROM responses").fetchone()["n"]
            live = self._conn.execute(
                "SELECT COUNT(*) AS n FROM responses WHERE expires_at > ?",
                (now,),
            ).fetchone()["n"]
            namespaces = [
                row["namespace"]
                for row in self._conn.execute(
                    "SELECT DISTINCT namespace FROM responses ORDER BY namespace"
                )
            ]
        return {
            "path": str(self.path),
            "total_rows": int(total),
            "live_rows": int(live),
            "namespaces": namespaces,
            "default_ttl": self.default_ttl,
        }

    def iter_keys(self, namespace: str) -> Iterator[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT cache_key FROM responses WHERE namespace = ? ORDER BY cache_key",
                (namespace,),
            ).fetchall()
        for row in rows:
            yield row["cache_key"]


def default_cache_path() -> Path:
    """Project-local default cache location."""
    return Path(".cistron_cache") / _DEFAULT_DB_NAME


def make_cache_key(*parts: Any) -> str:
    """Stable cache key from ordered identifier parts."""
    cleaned = []
    for part in parts:
        text = str(part).strip()
        if text:
            cleaned.append(text)
    if not cleaned:
        raise ValueError("at least one non-empty cache key part is required")
    return "|".join(cleaned)
