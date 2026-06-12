"""ssl.py tool tests."""

from __future__ import annotations

import httpx

from porkbun_mcp.client import PorkbunClient
from porkbun_mcp.tools import ssl as ssl_tool


def test_get_ssl_bundle(fake_client: PorkbunClient) -> None:
    fake_client._handlers.append(  # type: ignore[attr-defined]
        lambda r: httpx.Response(
            200,
            json={
                "status": "SUCCESS",
                "certificatechain": "-----BEGIN CERTIFICATE-----...",
                "privatekey": "-----BEGIN PRIVATE KEY-----...",
                "publickey": "-----BEGIN PUBLIC KEY-----...",
            },
        )
        if "/ssl/retrieve/" in r.url.path
        else None
    )
    out = ssl_tool.get_ssl_bundle_impl(fake_client, "example.com")
    assert "certificatechain" in out
    assert "privatekey" in out
