"""Shared pytest fixtures."""

from __future__ import annotations

import subprocess
from pathlib import Path

import httpx
import pytest

from porkbun_mcp.client import PorkbunClient


@pytest.fixture(autouse=True)
def isolated_pricing_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the pricing cache at a per-test XDG dir.

    pricing_cache resolves its path from os.environ at call time, so
    setting XDG_CACHE_HOME here guarantees tests never read a stale
    real cache or write into the developer's ~/.cache. Returns the
    XDG base dir for tests that want to inspect the cache file."""
    xdg = tmp_path / "xdg-cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(xdg))
    monkeypatch.delenv("PORKBUN_PRICING_CACHE_TTL", raising=False)
    return xdg


@pytest.fixture(autouse=True)
def _reset_audit_handler():
    """Reset the cached audit handler between tests."""
    from porkbun_mcp import audit

    audit._handler = None
    yield
    audit._handler = None


@pytest.fixture
def subprocess_spy(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Capture every subprocess invocation made by the audit module.

    Sets the handler to an external binary so tests can assert on argv shape."""
    from porkbun_mcp import audit

    audit._handler = None
    monkeypatch.setenv("PORKBUN_MCP_AUDIT_HANDLER", "/usr/local/bin/audit-spy")

    captured: list[list[str]] = []

    def fake_run(cmd, **kw):
        captured.append(list(cmd))
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    return captured


@pytest.fixture
def fake_client() -> PorkbunClient:
    """A PorkbunClient wired to a closure-capturing transport.

    Tests append matchers to ``client._handlers`` — each is a callable
    ``(httpx.Request) -> httpx.Response | None``. First non-None wins. If
    no matcher fires, the transport returns 404, which surfaces as a clear
    test failure rather than a silent miss.
    """
    handlers: list = []

    def transport_handler(request: httpx.Request) -> httpx.Response:
        for matcher in handlers:
            resp = matcher(request)
            if resp is not None:
                return resp
        return httpx.Response(404, json={"status": "ERROR", "message": "no matcher"})

    client = PorkbunClient(
        "https://api.porkbun.com/api/json/v3",
        "pk1_x",
        "sk1_x",
        transport=httpx.MockTransport(transport_handler),
    )
    client._handlers = handlers  # type: ignore[attr-defined]
    return client
