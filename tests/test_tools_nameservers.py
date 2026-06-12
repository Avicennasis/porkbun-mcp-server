"""nameservers.py tool tests — read (Phase 1) + update (Phase 3)."""

from __future__ import annotations

import json

import httpx
import pytest

from porkbun_mcp.client import PorkbunClient
from porkbun_mcp.errors import PorkbunAPIError
from porkbun_mcp.tools import nameservers


def test_get_name_servers(fake_client: PorkbunClient) -> None:
    fake_client._handlers.append(  # type: ignore[attr-defined]
        lambda r: httpx.Response(
            200,
            json={
                "status": "SUCCESS",
                "ns": [
                    "curitiba.ns.porkbun.com",
                    "fortaleza.ns.porkbun.com",
                    "maceio.ns.porkbun.com",
                    "salvador.ns.porkbun.com",
                ],
            },
        )
        if "/domain/getNs/" in r.url.path
        else None
    )
    out = nameservers.get_name_servers_impl(fake_client, "example.com")
    assert len(out["ns"]) == 4
    assert all(host.endswith(".ns.porkbun.com") for host in out["ns"])


# ---------------------------------------------------------------------------
# Mutation (Phase 3)
# ---------------------------------------------------------------------------


def test_update_name_servers_calls_api_and_emits_audit(
    fake_client: PorkbunClient, subprocess_spy: list[list[str]]
) -> None:
    bodies: list[dict] = []

    def handler(r: httpx.Request) -> httpx.Response | None:
        if "/domain/updateNs/example.com" in r.url.path:
            bodies.append(json.loads(r.content.decode()))
            return httpx.Response(200, json={"status": "SUCCESS"})
        return None

    fake_client._handlers.append(handler)  # type: ignore[attr-defined]

    new_ns = [
        "curitiba.ns.porkbun.com",
        "fortaleza.ns.porkbun.com",
        "maceio.ns.porkbun.com",
        "salvador.ns.porkbun.com",
    ]
    nameservers.update_name_servers_impl(
        fake_client, "example.com",
        ns=new_ns,
        reason="Phase 5 smoke prep — pulling NS to Porkbun",
    )

    assert bodies[0]["ns"] == new_ns

    cmd = subprocess_spy[0]
    assert cmd[cmd.index("--action") + 1] == "NS"
    assert cmd[cmd.index("--service") + 1] == "example.com"
    assert "--target" not in cmd
    payload = json.loads(cmd[cmd.index("--payload") + 1])
    assert payload["new_ns"] == new_ns


def test_update_name_servers_audit_disabled(
    fake_client: PorkbunClient, subprocess_spy: list[list[str]]
) -> None:
    fake_client._handlers.append(  # type: ignore[attr-defined]
        lambda r: httpx.Response(200, json={"status": "SUCCESS"})
        if "/domain/updateNs/example.com" in r.url.path else None
    )

    nameservers.update_name_servers_impl(
        fake_client, "example.com",
        ns=["ns1.example.com"],
        reason="r",
        audit_enabled=False,
    )
    assert subprocess_spy == []


def test_update_name_servers_api_error_skips_audit(
    fake_client: PorkbunClient, subprocess_spy: list[list[str]]
) -> None:
    fake_client._handlers.append(  # type: ignore[attr-defined]
        lambda r: httpx.Response(
            400, json={"status": "ERROR", "message": "Invalid NS"},
        )
        if "/domain/updateNs/example.com" in r.url.path else None
    )

    with pytest.raises(PorkbunAPIError):
        nameservers.update_name_servers_impl(
            fake_client, "example.com",
            ns=["bogus"],
            reason="r",
        )
    assert subprocess_spy == []
