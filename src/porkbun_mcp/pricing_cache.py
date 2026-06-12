"""Disk-backed TTL cache for the Porkbun pricing table (claudecode#3168).

``/pricing/get`` returns a ~30KB payload that changes on the order of
months, so hitting the live API on every call wastes both latency and our
Porkbun rate-limit budget. This module persists the last successful
response under the XDG cache dir and serves it until the TTL lapses.

Deliberately scoped to this one endpoint — mutable data (DNS records,
domain inventory) must stay live and is NOT cached here.

- Default TTL: 24 hours, overridable via ``PORKBUN_PRICING_CACHE_TTL``
  (seconds). ``0`` disables caching reads (every call refetches).
- Cache file: ``$XDG_CACHE_HOME/porkbun-mcp/pricing.json``, defaulting to
  ``~/.cache/porkbun-mcp/pricing.json``.
- A corrupt / unreadable / unwritable cache never breaks the tool — reads
  fall back to a live fetch, writes are best-effort.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .client import PorkbunClient

log = logging.getLogger("porkbun_mcp.pricing_cache")

DEFAULT_TTL_SECONDS = 86400.0  # 24 hours
TTL_ENV_VAR = "PORKBUN_PRICING_CACHE_TTL"
CACHE_FILENAME = "pricing.json"


def cache_ttl_seconds(env: Mapping[str, str] | None = None) -> float:
    """TTL in seconds from ``PORKBUN_PRICING_CACHE_TTL``, default 24h.

    Non-numeric or negative values fall back to the default with a
    warning rather than raising — a bad env var must not take the
    pricing tools down.
    """
    e = env if env is not None else os.environ
    raw = e.get(TTL_ENV_VAR, "").strip()
    if not raw:
        return DEFAULT_TTL_SECONDS
    try:
        ttl = float(raw)
    except ValueError:
        log.warning(
            "Ignoring non-numeric %s=%r; using default %.0fs",
            TTL_ENV_VAR, raw, DEFAULT_TTL_SECONDS,
        )
        return DEFAULT_TTL_SECONDS
    if ttl < 0:
        log.warning(
            "Ignoring negative %s=%r; using default %.0fs",
            TTL_ENV_VAR, raw, DEFAULT_TTL_SECONDS,
        )
        return DEFAULT_TTL_SECONDS
    return ttl


def cache_path(env: Mapping[str, str] | None = None) -> Path:
    """``$XDG_CACHE_HOME/porkbun-mcp/pricing.json`` (default ``~/.cache``)."""
    e = env if env is not None else os.environ
    xdg = (e.get("XDG_CACHE_HOME") or "").strip()
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / "porkbun-mcp" / CACHE_FILENAME


def _read_cache(path: Path) -> dict[str, Any] | None:
    """Parse the cache file; ``None`` on any shape/IO problem (= miss)."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    fetched_at = raw.get("fetched_at")
    payload = raw.get("payload")
    if not isinstance(fetched_at, (int, float)) or isinstance(fetched_at, bool):
        return None
    if not isinstance(payload, dict):
        return None
    return raw


def _write_cache(path: Path, payload: dict[str, Any]) -> None:
    """Best-effort persist — an unwritable cache dir must not break the tool.

    Writes to a sibling temp file then ``os.replace``s it in, so a
    concurrent reader never sees a half-written JSON document.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(
            json.dumps({"fetched_at": time.time(), "payload": payload}),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    except OSError as e:
        log.warning("Could not persist pricing cache at %s: %s", path, e)


def get_pricing(
    client: PorkbunClient,
    *,
    force_refresh: bool = False,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """The full pricing payload, served through the disk TTL cache.

    Cache hit: fresh-enough ``pricing.json`` exists and ``force_refresh``
    is False. Otherwise fetch live and persist. A ``fetched_at`` in the
    future (clock skew, copied file) counts as expired.
    """
    path = cache_path(env=env)
    if not force_refresh:
        cached = _read_cache(path)
        if cached is not None:
            age = time.time() - cached["fetched_at"]
            if 0 <= age < cache_ttl_seconds(env=env):
                return cached["payload"]

    payload = client.post("/pricing/get")
    # client.post raises on ERROR responses, but stay defensive: never
    # persist a payload that isn't an explicit SUCCESS.
    if payload.get("status") == "SUCCESS":
        _write_cache(path, payload)
    return payload
