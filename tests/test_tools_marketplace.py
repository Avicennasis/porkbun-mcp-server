"""marketplace.py tool tests."""

from __future__ import annotations

import json

import httpx

from porkbun_mcp.client import PorkbunClient
from porkbun_mcp.tools import marketplace


def test_get_marketplace_unfiltered(fake_client: PorkbunClient) -> None:
    captured: list = []

    def handler(r: httpx.Request) -> httpx.Response | None:
        if r.url.path.endswith("/marketplace/getAll"):
            captured.append(json.loads(r.content))
            return httpx.Response(
                200,
                json={
                    "status": "SUCCESS",
                    "domains": [
                        {"domain": "cool.com", "price": 5000},
                        {"domain": "neat.io", "price": 2500},
                    ],
                },
            )
        return None

    fake_client._handlers.append(handler)  # type: ignore[attr-defined]
    out = marketplace.get_marketplace_impl(fake_client)
    assert len(out["domains"]) == 2
    assert captured[0]["start"] == 0
    assert captured[0]["limit"] == 1000


def test_get_marketplace_filtered(fake_client: PorkbunClient) -> None:
    captured: list = []

    def handler(r: httpx.Request) -> httpx.Response | None:
        if r.url.path.endswith("/marketplace/getAll"):
            captured.append(json.loads(r.content))
            return httpx.Response(200, json={"status": "SUCCESS", "domains": []})
        return None

    fake_client._handlers.append(handler)  # type: ignore[attr-defined]
    marketplace.get_marketplace_impl(
        fake_client,
        query="ai -test",
        tlds=["com", "io"],
        sld_length_min=3,
        sld_length_max=8,
        sort_name="price",
        sort_direction="asc",
    )
    body = captured[0]
    assert body["query"] == "ai -test"
    assert body["tlds"] == ["com", "io"]
    assert body["sldLengthMin"] == 3
    assert body["sldLengthMax"] == 8
    assert body["sortName"] == "price"
    assert body["sortDirection"] == "asc"
