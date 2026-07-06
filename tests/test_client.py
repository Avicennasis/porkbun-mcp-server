"""Unit tests for PorkbunClient — mocks httpx transport directly."""

from __future__ import annotations

import json

import httpx
import pytest

from porkbun_mcp.client import PorkbunClient
from porkbun_mcp.errors import (
    PorkbunAPIError,
    PorkbunAuthError,
    PorkbunRateLimit,
)


def _ok(payload: dict) -> httpx.Response:
    return httpx.Response(200, json={"status": "SUCCESS", **payload})


def test_client_injects_credentials_into_body() -> None:
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return _ok({"yourIp": "1.2.3.4"})

    transport = httpx.MockTransport(handler)
    client = PorkbunClient(
        base_url="https://api.porkbun.com/api/json/v3",
        api_key="pk1_x",
        secret_key="sk1_x",
        transport=transport,
    )
    out = client.post("/ping")
    assert out["yourIp"] == "1.2.3.4"
    assert captured[0]["apikey"] == "pk1_x"
    assert captured[0]["secretapikey"] == "sk1_x"


def test_client_merges_extra_body() -> None:
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return _ok({})

    transport = httpx.MockTransport(handler)
    client = PorkbunClient(
        "https://api.porkbun.com/api/json/v3", "pk1_x", "sk1_x", transport=transport
    )
    client.post("/dns/create/example.com", body={"type": "A", "name": "test", "content": "1.2.3.4"})
    body = captured[0]
    assert body["apikey"] == "pk1_x"
    assert body["type"] == "A"
    assert body["content"] == "1.2.3.4"


def test_client_raises_on_status_error_in_body() -> None:
    """Porkbun returns 200 with status:'ERROR' on app-level failures."""
    transport = httpx.MockTransport(
        lambda r: httpx.Response(200, json={"status": "ERROR", "message": "Domain not found."})
    )
    client = PorkbunClient(
        "https://api.porkbun.com/api/json/v3", "pk1_x", "sk1_x", transport=transport
    )
    with pytest.raises(PorkbunAPIError, match="Domain not found"):
        client.post("/dns/retrieve/missing.com")


def test_client_raises_auth_error_on_403() -> None:
    transport = httpx.MockTransport(
        lambda r: httpx.Response(403, json={"status": "ERROR", "message": "Invalid API key."})
    )
    client = PorkbunClient(
        "https://api.porkbun.com/api/json/v3", "pk1_x", "sk1_x", transport=transport
    )
    with pytest.raises(PorkbunAuthError):
        client.post("/ping")


def test_client_retries_then_succeeds_on_429() -> None:
    """Two 429s, then a 200 — client should retry and succeed."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] <= 2:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"status": "ERROR"})
        return _ok({"yourIp": "1.2.3.4"})

    transport = httpx.MockTransport(handler)
    client = PorkbunClient(
        "https://api.porkbun.com/api/json/v3",
        "pk1_x",
        "sk1_x",
        transport=transport,
        max_retries=3,
        retry_base_seconds=0.0,
    )
    out = client.post("/ping")
    assert out["yourIp"] == "1.2.3.4"
    assert calls["n"] == 3


def test_client_raises_rate_limit_after_max_retries() -> None:
    transport = httpx.MockTransport(
        lambda r: httpx.Response(429, headers={"Retry-After": "0"}, json={"status": "ERROR"})
    )
    client = PorkbunClient(
        "https://api.porkbun.com/api/json/v3",
        "pk1_x",
        "sk1_x",
        transport=transport,
        max_retries=2,
        retry_base_seconds=0.0,
    )
    with pytest.raises(PorkbunRateLimit):
        client.post("/ping")


# ---------------------------------------------------------------------------
# B1-123 / B1-124 / B1-125 regression tests
# ---------------------------------------------------------------------------


def _client(transport: httpx.MockTransport, **kw) -> PorkbunClient:
    return PorkbunClient(
        "https://api.porkbun.com/api/json/v3",
        "pk1_x",
        "sk1_x",
        transport=transport,
        retry_base_seconds=0.0,
        **kw,
    )


def test_client_wraps_network_errors_as_porkbun_error() -> None:
    """B1-123: httpx exceptions must surface as PorkbunError subtypes."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("name resolution failed")

    client = _client(httpx.MockTransport(handler))
    with pytest.raises(PorkbunAPIError, match="Network error calling Porkbun"):
        client.post("/ping")


def test_client_retries_5xx_for_idempotent_calls() -> None:
    """B1-124: transient 502s on idempotent reads are retried."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] <= 2:
            return httpx.Response(502, text="Bad Gateway")
        return _ok({"yourIp": "1.2.3.4"})

    client = _client(httpx.MockTransport(handler), max_retries=3)
    out = client.post("/ping", idempotent=True)
    assert out["yourIp"] == "1.2.3.4"
    assert calls["n"] == 3


def test_client_does_not_retry_5xx_for_mutations() -> None:
    """B1-124: mutations must NOT be retried on 5xx (double-apply risk)."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(502, text="Bad Gateway")

    client = _client(httpx.MockTransport(handler), max_retries=3)
    with pytest.raises(PorkbunAPIError):
        client.post("/dns/create/example.com", body={"type": "A"})
    assert calls["n"] == 1


def test_client_5xx_exhaustion_surfaces_api_error() -> None:
    """B1-124: a persistent 502 surfaces as PorkbunAPIError after retries."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(502, text="Bad Gateway")

    client = _client(httpx.MockTransport(handler), max_retries=2)
    with pytest.raises(PorkbunAPIError) as excinfo:
        client.post("/ping", idempotent=True)
    assert not isinstance(excinfo.value, PorkbunRateLimit)
    assert excinfo.value.status_code == 502
    assert calls["n"] == 2


def test_client_rate_limit_carries_last_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B1-125: exhausted-retry PorkbunRateLimit forwards the last Retry-After."""
    import time as _time

    monkeypatch.setattr(_time, "sleep", lambda s: None)

    transport = httpx.MockTransport(
        lambda r: httpx.Response(429, headers={"Retry-After": "7.5"}, json={"status": "ERROR"})
    )
    client = _client(transport, max_retries=2)
    with pytest.raises(PorkbunRateLimit) as excinfo:
        client.post("/ping")
    assert excinfo.value.retry_after_seconds == 7.5
