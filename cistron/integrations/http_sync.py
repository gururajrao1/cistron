"""Synchronous HTTP helpers for zero-key public biology APIs."""

from __future__ import annotations

from typing import Any, Dict, Optional
import json
import logging
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 18.0
_UA = "CISTRON-Lab/0.21 (+https://github.com/cistron; research)"


def http_get_bytes(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    accept: str = "*/*",
) -> Optional[bytes]:
    """GET raw bytes; return None on any network / HTTP failure."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": _UA, "Accept": accept},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if getattr(resp, "status", 200) >= 400:
                return None
            return resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        logger.debug("HTTP GET failed %s: %s", url, exc)
        return None


def http_get_text(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    accept: str = "text/plain, */*",
) -> Optional[str]:
    raw = http_get_bytes(url, timeout=timeout, accept=accept)
    if raw is None:
        return None
    return raw.decode("utf-8", errors="replace")


def http_get_json(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> Optional[Any]:
    raw = http_get_bytes(url, timeout=timeout, accept="application/json")
    if raw is None:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        logger.debug("JSON decode failed for %s: %s", url, exc)
        return None


def cache_or_fetch_json(
    cache: Any,
    namespace: str,
    key: str,
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> Optional[Any]:
    """Return cached JSON payload or live-fetch and store."""
    hit = cache.get_json(namespace, key)
    if hit is not None:
        return hit
    payload = http_get_json(url, timeout=timeout)
    if payload is not None:
        cache.set_json(namespace, key, payload)
    return payload
