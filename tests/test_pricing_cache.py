"""pricing_cache.py tests — disk TTL cache for /pricing/get (claudecode#3168).

The autouse ``isolated_pricing_cache`` fixture (conftest.py) points
XDG_CACHE_HOME at a per-test tmp dir, so these tests exercise the real
read/write path without touching the developer's ~/.cache.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import pytest

from porkbun_mcp import pricing_cache
from porkbun_mcp.client import PorkbunClient
from porkbun_mcp.tools import account

PRICING_PAYLOAD = {
    "status": "SUCCESS",
    "pricing": {
        "com": {"registration": "9.13", "renewal": "9.13", "transfer": "9.13"},
        "net": {"registration": "11.32", "renewal": "11.32", "transfer": "11.32"},
    },
}


def install_pricing_handler(
    client: PorkbunClient, payload: dict | None = None
) -> list[str]:
    """Append a counting /pricing/get matcher; returns the call log."""
    calls: list[str] = []

    def handler(r: httpx.Request) -> httpx.Response | None:
        if r.url.path.endswith("/pricing/get"):
            calls.append(r.url.path)
            return httpx.Response(200, json=payload or PRICING_PAYLOAD)
        return None

    client._handlers.append(handler)  # type: ignore[attr-defined]
    return calls


def rewrite_fetched_at(path: Path, fetched_at: float) -> None:
    """Backdate (or future-date) the cache file's timestamp."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["fetched_at"] = fetched_at
    path.write_text(json.dumps(raw), encoding="utf-8")


# ---------------------------------------------------------------------------
# Core read-through behavior
# ---------------------------------------------------------------------------


def test_miss_fetches_and_persists(fake_client: PorkbunClient) -> None:
    calls = install_pricing_handler(fake_client)
    out = account.get_pricing_impl(fake_client)
    assert out["pricing"]["com"]["registration"] == "9.13"
    assert len(calls) == 1

    path = pricing_cache.cache_path()
    assert path.is_file()
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["payload"] == PRICING_PAYLOAD
    assert abs(raw["fetched_at"] - time.time()) < 60


def test_hit_serves_from_cache_without_api_call(fake_client: PorkbunClient) -> None:
    calls = install_pricing_handler(fake_client)
    first = account.get_pricing_impl(fake_client)
    second = account.get_pricing_impl(fake_client)
    assert first == second == PRICING_PAYLOAD
    assert len(calls) == 1


def test_expired_cache_refetches(fake_client: PorkbunClient) -> None:
    calls = install_pricing_handler(fake_client)
    account.get_pricing_impl(fake_client)
    # Backdate past the default 24h TTL.
    rewrite_fetched_at(pricing_cache.cache_path(), time.time() - 90_000)
    account.get_pricing_impl(fake_client)
    assert len(calls) == 2


def test_force_refresh_bypasses_fresh_cache(fake_client: PorkbunClient) -> None:
    calls = install_pricing_handler(fake_client)
    account.get_pricing_impl(fake_client)
    out = account.get_pricing_impl(fake_client, force_refresh=True)
    assert out == PRICING_PAYLOAD
    assert len(calls) == 2


def test_force_refresh_rewrites_cache(fake_client: PorkbunClient) -> None:
    calls = install_pricing_handler(fake_client)
    account.get_pricing_impl(fake_client)
    path = pricing_cache.cache_path()
    rewrite_fetched_at(path, 1000.0)  # sentinel
    account.get_pricing_impl(fake_client, force_refresh=True)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["fetched_at"] != 1000.0
    assert len(calls) == 2


def test_future_fetched_at_counts_as_expired(fake_client: PorkbunClient) -> None:
    calls = install_pricing_handler(fake_client)
    account.get_pricing_impl(fake_client)
    rewrite_fetched_at(pricing_cache.cache_path(), time.time() + 3600)
    account.get_pricing_impl(fake_client)
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# TTL env var
# ---------------------------------------------------------------------------


def test_ttl_default_is_24h() -> None:
    assert pricing_cache.cache_ttl_seconds(env={}) == 86400.0


def test_ttl_env_var_overrides() -> None:
    assert pricing_cache.cache_ttl_seconds(
        env={"PORKBUN_PRICING_CACHE_TTL": "3600"}
    ) == 3600.0


@pytest.mark.parametrize("raw", ["banana", "-5", ""])
def test_ttl_bad_values_fall_back_to_default(raw: str) -> None:
    assert pricing_cache.cache_ttl_seconds(
        env={"PORKBUN_PRICING_CACHE_TTL": raw}
    ) == 86400.0


def test_ttl_zero_disables_cache_reads(
    fake_client: PorkbunClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PORKBUN_PRICING_CACHE_TTL", "0")
    calls = install_pricing_handler(fake_client)
    account.get_pricing_impl(fake_client)
    account.get_pricing_impl(fake_client)
    assert len(calls) == 2


def test_short_ttl_expires(
    fake_client: PorkbunClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PORKBUN_PRICING_CACHE_TTL", "100")
    calls = install_pricing_handler(fake_client)
    account.get_pricing_impl(fake_client)
    rewrite_fetched_at(pricing_cache.cache_path(), time.time() - 50)
    account.get_pricing_impl(fake_client)  # age 50 < 100 → hit
    assert len(calls) == 1
    rewrite_fetched_at(pricing_cache.cache_path(), time.time() - 150)
    account.get_pricing_impl(fake_client)  # age 150 > 100 → refetch
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# Cache location
# ---------------------------------------------------------------------------


def test_cache_path_respects_xdg_cache_home(tmp_path: Path) -> None:
    p = pricing_cache.cache_path(env={"XDG_CACHE_HOME": str(tmp_path / "x")})
    assert p == tmp_path / "x" / "porkbun-mcp" / "pricing.json"


def test_cache_path_defaults_to_home_dot_cache() -> None:
    p = pricing_cache.cache_path(env={})
    assert p == Path.home() / ".cache" / "porkbun-mcp" / "pricing.json"
    # Blank XDG_CACHE_HOME is treated as unset (XDG spec).
    assert pricing_cache.cache_path(env={"XDG_CACHE_HOME": "  "}) == p


# ---------------------------------------------------------------------------
# Robustness: corrupt cache, bad shapes, unwritable dir
# ---------------------------------------------------------------------------


def test_corrupt_cache_file_refetches(fake_client: PorkbunClient) -> None:
    calls = install_pricing_handler(fake_client)
    path = pricing_cache.cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    out = account.get_pricing_impl(fake_client)
    assert out == PRICING_PAYLOAD
    assert len(calls) == 1
    # And the bad file was repaired in place.
    assert json.loads(path.read_text(encoding="utf-8"))["payload"] == PRICING_PAYLOAD


@pytest.mark.parametrize(
    "bad",
    [
        [1, 2, 3],                                       # not a dict
        {"payload": PRICING_PAYLOAD},                    # missing fetched_at
        {"fetched_at": "yesterday", "payload": PRICING_PAYLOAD},  # non-numeric
        {"fetched_at": True, "payload": PRICING_PAYLOAD},         # bool sneaks past int
        {"fetched_at": 1.0, "payload": "nope"},          # payload not a dict
    ],
)
def test_bad_cache_shapes_refetch(fake_client: PorkbunClient, bad: object) -> None:
    calls = install_pricing_handler(fake_client)
    path = pricing_cache.cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bad), encoding="utf-8")
    out = account.get_pricing_impl(fake_client)
    assert out == PRICING_PAYLOAD
    assert len(calls) == 1


def test_unwritable_cache_dir_does_not_break(
    fake_client: PorkbunClient,
) -> None:
    """If the cache dir can't be created, the tool still returns live data."""
    calls = install_pricing_handler(fake_client)
    path = pricing_cache.cache_path()
    path.parent.parent.mkdir(parents=True, exist_ok=True)
    path.parent.touch()  # file where the dir should be → mkdir fails
    out = account.get_pricing_impl(fake_client)
    assert out == PRICING_PAYLOAD
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# Derived tools read through the same cache
# ---------------------------------------------------------------------------


def test_derived_tools_share_one_cached_fetch(fake_client: PorkbunClient) -> None:
    calls = install_pricing_handler(fake_client)
    full = account.get_pricing_impl(fake_client)
    tld = account.get_pricing_for_tld_impl(fake_client, "com")
    tlds = account.list_supported_tlds_impl(fake_client)
    assert full["pricing"]["net"]["renewal"] == "11.32"
    assert tld["pricing"]["registration"] == "9.13"
    assert tlds["tlds"] == ["com", "net"]
    assert len(calls) == 1  # one live fetch serves all three tools


def test_derived_tools_force_refresh_passthrough(fake_client: PorkbunClient) -> None:
    calls = install_pricing_handler(fake_client)
    account.get_pricing_impl(fake_client)
    account.get_pricing_for_tld_impl(fake_client, "com", force_refresh=True)
    account.list_supported_tlds_impl(fake_client, force_refresh=True)
    assert len(calls) == 3
