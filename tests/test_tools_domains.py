"""domains.py tool tests — reads (Phase 1) + registrar mutations (Phase 4)."""

from __future__ import annotations

import json

import httpx
import pytest

from porkbun_mcp.client import PorkbunClient
from porkbun_mcp.errors import PorkbunAPIError
from porkbun_mcp.tools import domains


def test_list_domains(fake_client: PorkbunClient) -> None:
    fake_client._handlers.append(  # type: ignore[attr-defined]
        lambda r: httpx.Response(
            200,
            json={
                "status": "SUCCESS",
                "domains": [
                    {"domain": "example.com", "status": "ACTIVE"},
                    {"domain": "example.net", "status": "ACTIVE"},
                ],
            },
        )
        if r.url.path.endswith("/domain/listAll")
        else None
    )
    out = domains.list_domains_impl(fake_client)
    assert len(out["domains"]) == 2
    assert out["domains"][0]["domain"] == "example.com"


def test_list_domains_pagination_arg(fake_client: PorkbunClient) -> None:
    """``start`` is sent in the body."""
    captured: list = []

    def handler(r: httpx.Request) -> httpx.Response | None:
        if r.url.path.endswith("/domain/listAll"):
            captured.append(json.loads(r.content))
            return httpx.Response(200, json={"status": "SUCCESS", "domains": []})
        return None

    fake_client._handlers.append(handler)  # type: ignore[attr-defined]
    domains.list_domains_impl(fake_client, start=100, include_labels=True)
    assert captured[0]["start"] == 100
    assert captured[0]["includeLabels"] == "yes"


def test_get_url_forwarding(fake_client: PorkbunClient) -> None:
    fake_client._handlers.append(  # type: ignore[attr-defined]
        lambda r: httpx.Response(
            200,
            json={
                "status": "SUCCESS",
                "forwards": [
                    {"id": "1", "subdomain": "www", "location": "https://example.com"}
                ],
            },
        )
        if "/domain/getUrlForwarding/" in r.url.path
        else None
    )
    out = domains.get_url_forwarding_impl(fake_client, "example.com")
    assert out["forwards"][0]["subdomain"] == "www"


def test_get_domain(fake_client: PorkbunClient) -> None:
    fake_client._handlers.append(  # type: ignore[attr-defined]
        lambda r: httpx.Response(
            200,
            json={
                "status": "SUCCESS",
                "domain": "example.com",
                "status_code": "ACTIVE",
                "createDate": "2024-01-15 10:00:00",
                "expireDate": "2026-01-15 10:00:00",
                "autoRenew": True,
            },
        )
        if r.url.path.endswith("/domain/get/example.com")
        else None
    )
    out = domains.get_domain_impl(fake_client, "example.com")
    assert out["domain"] == "example.com"
    assert out["autoRenew"] is True


def test_get_glue(fake_client: PorkbunClient) -> None:
    fake_client._handlers.append(  # type: ignore[attr-defined]
        lambda r: httpx.Response(
            200,
            json={
                "status": "SUCCESS",
                "glue": [
                    {"host": "ns1.example.com", "ips": ["1.2.3.4"]},
                    {"host": "ns2.example.com", "ips": ["5.6.7.8"]},
                ],
            },
        )
        if "/domain/getGlue/" in r.url.path
        else None
    )
    out = domains.get_glue_impl(fake_client, "example.com")
    assert len(out["glue"]) == 2
    assert out["glue"][0]["host"] == "ns1.example.com"


def test_list_labels(fake_client: PorkbunClient) -> None:
    fake_client._handlers.append(  # type: ignore[attr-defined]
        lambda r: httpx.Response(
            200,
            json={
                "status": "SUCCESS",
                "labels": [{"id": "1", "title": "production", "color": "orange"}],
            },
        )
        if r.url.path.endswith("/domain/labels/list")
        else None
    )
    out = domains.list_labels_impl(fake_client)
    assert out["labels"][0]["title"] == "production"


# ---------------------------------------------------------------------------
# Registrar mutations (Phase 4)
# ---------------------------------------------------------------------------


def _match_path(suffix: str, response_json: dict):
    def handler(r: httpx.Request) -> httpx.Response | None:
        if suffix in r.url.path:
            return httpx.Response(200, json=response_json)
        return None
    return handler


def _capture_request(suffix: str, response_json: dict):
    captured: list[dict] = []

    def handler(r: httpx.Request) -> httpx.Response | None:
        if suffix in r.url.path:
            captured.append(json.loads(r.content.decode()))
            return httpx.Response(200, json=response_json)
        return None

    return handler, captured


# --- Registration / renewal / transfer ------------------------------------


def test_register_domain_sends_cost_and_agree(
    fake_client: PorkbunClient, subprocess_spy: list[list[str]]
) -> None:
    handler, bodies = _capture_request(
        "/domain/create/newsite.com",
        {"status": "SUCCESS", "domain": "newsite.com"},
    )
    fake_client._handlers.append(handler)  # type: ignore[attr-defined]

    out = domains.register_domain_impl(
        fake_client, "newsite.com",
        cost=913, agree_to_terms="yes",
        reason="New project domain",
    )

    assert out["status"] == "SUCCESS"
    assert bodies[0]["cost"] == 913
    assert bodies[0]["agreeToTerms"] == "yes"
    cmd = subprocess_spy[0]
    assert cmd[cmd.index("--action") + 1] == "REGISTER"
    payload = json.loads(cmd[cmd.index("--payload") + 1])
    assert payload["cost"] == 913


def test_renew_domain_sends_cost(
    fake_client: PorkbunClient, subprocess_spy: list[list[str]]
) -> None:
    handler, bodies = _capture_request(
        "/domain/renew/example.com",
        {"status": "SUCCESS"},
    )
    fake_client._handlers.append(handler)  # type: ignore[attr-defined]

    domains.renew_domain_impl(
        fake_client, "example.com",
        cost=913,
        reason="Annual renewal",
    )

    assert bodies[0]["cost"] == 913
    cmd = subprocess_spy[0]
    assert cmd[cmd.index("--action") + 1] == "RENEW"


def test_transfer_domain_sends_auth_code_and_cost(
    fake_client: PorkbunClient, subprocess_spy: list[list[str]]
) -> None:
    handler, bodies = _capture_request(
        "/domain/transfer/moveme.com",
        {"status": "SUCCESS"},
    )
    fake_client._handlers.append(handler)  # type: ignore[attr-defined]

    domains.transfer_domain_impl(
        fake_client, "moveme.com",
        auth_code="EPP-SECRET-123",
        cost=913,
        reason="Consolidating registrars",
    )

    assert bodies[0]["authCode"] == "EPP-SECRET-123"
    assert bodies[0]["cost"] == 913
    cmd = subprocess_spy[0]
    assert cmd[cmd.index("--action") + 1] == "TRANSFER"


def test_get_transfer_status(fake_client: PorkbunClient) -> None:
    fake_client._handlers.append(  # type: ignore[attr-defined]
        lambda r: httpx.Response(
            200,
            json={
                "status": "SUCCESS",
                "transfer": {"domain": "moveme.com", "status": "pending"},
            },
        )
        if "/domain/getTransfer/" in r.url.path
        else None
    )
    out = domains.get_transfer_status_impl(fake_client, "moveme.com")
    assert out["transfer"]["status"] == "pending"


def test_list_transfers(fake_client: PorkbunClient) -> None:
    fake_client._handlers.append(  # type: ignore[attr-defined]
        lambda r: httpx.Response(
            200,
            json={
                "status": "SUCCESS",
                "transfers": [
                    {"domain": "moveme.com", "status": "pending"},
                ],
            },
        )
        if r.url.path.endswith("/domain/listTransfers")
        else None
    )
    out = domains.list_transfers_impl(fake_client)
    assert len(out["transfers"]) == 1


# --- Auto-renew ------------------------------------------------------------


def test_update_auto_renew_enable(
    fake_client: PorkbunClient, subprocess_spy: list[list[str]]
) -> None:
    handler, bodies = _capture_request(
        "/domain/updateAutoRenew/example.com",
        {"status": "SUCCESS"},
    )
    fake_client._handlers.append(handler)  # type: ignore[attr-defined]

    domains.update_auto_renew_impl(
        fake_client, "example.com",
        auto_renew=True,
        reason="Prevent accidental expiry",
    )

    assert bodies[0]["autoRenew"] == 1
    cmd = subprocess_spy[0]
    assert cmd[cmd.index("--category") + 1] == "domain"
    assert cmd[cmd.index("--action") + 1] == "AUTO_RENEW"
    payload = json.loads(cmd[cmd.index("--payload") + 1])
    assert payload["auto_renew"] is True


def test_update_auto_renew_disable(
    fake_client: PorkbunClient, subprocess_spy: list[list[str]]
) -> None:
    handler, bodies = _capture_request(
        "/domain/updateAutoRenew/example.com",
        {"status": "SUCCESS"},
    )
    fake_client._handlers.append(handler)  # type: ignore[attr-defined]

    domains.update_auto_renew_impl(
        fake_client, "example.com",
        auto_renew=False,
        reason="Domain being transferred out",
    )

    assert bodies[0]["autoRenew"] == 0
    cmd = subprocess_spy[0]
    payload = json.loads(cmd[cmd.index("--payload") + 1])
    assert payload["auto_renew"] is False


# --- Glue ------------------------------------------------------------------


def test_create_glue_emits_audit(
    fake_client: PorkbunClient, subprocess_spy: list[list[str]]
) -> None:
    handler, bodies = _capture_request(
        "/domain/createGlue/example.com/ns1",
        {"status": "SUCCESS"},
    )
    fake_client._handlers.append(handler)  # type: ignore[attr-defined]

    domains.create_glue_impl(
        fake_client, "example.com",
        host="ns1", ips=["1.2.3.4"],
        reason="Custom NS",
    )

    assert bodies[0]["ips"] == ["1.2.3.4"]
    cmd = subprocess_spy[0]
    assert cmd[cmd.index("--category") + 1] == "domain"
    assert cmd[cmd.index("--action") + 1] == "GLUE_CREATE"
    assert cmd[cmd.index("--target") + 1] == "GLUE `ns1`"
    payload = json.loads(cmd[cmd.index("--payload") + 1])
    assert payload["ips"] == ["1.2.3.4"]


def test_update_glue_emits_audit(
    fake_client: PorkbunClient, subprocess_spy: list[list[str]]
) -> None:
    fake_client._handlers.append(  # type: ignore[attr-defined]
        _match_path("/domain/updateGlue/example.com/ns1", {"status": "SUCCESS"})
    )

    domains.update_glue_impl(
        fake_client, "example.com",
        host="ns1", ips=["5.6.7.8"],
        reason="IP rotation",
    )

    cmd = subprocess_spy[0]
    assert cmd[cmd.index("--action") + 1] == "GLUE_UPDATE"
    assert cmd[cmd.index("--target") + 1] == "GLUE `ns1`"


def test_delete_glue_emits_audit(
    fake_client: PorkbunClient, subprocess_spy: list[list[str]]
) -> None:
    fake_client._handlers.append(  # type: ignore[attr-defined]
        _match_path("/domain/deleteGlue/example.com/ns1", {"status": "SUCCESS"})
    )

    domains.delete_glue_impl(
        fake_client, "example.com",
        host="ns1",
        reason="Decommission",
    )

    cmd = subprocess_spy[0]
    assert cmd[cmd.index("--action") + 1] == "GLUE_DELETE"
    assert cmd[cmd.index("--target") + 1] == "GLUE `ns1`"


# --- URL forwarding --------------------------------------------------------


def test_add_url_forward_emits_audit(
    fake_client: PorkbunClient, subprocess_spy: list[list[str]]
) -> None:
    handler, bodies = _capture_request(
        "/domain/addUrlForward/example.com",
        {"status": "SUCCESS"},
    )
    fake_client._handlers.append(handler)  # type: ignore[attr-defined]

    domains.add_url_forward_impl(
        fake_client, "example.com",
        subdomain="www", location="https://example.org",
        type="permanent", include_path="yes", wildcard="no",
        reason="Apex-to-www redirect",
    )

    body = bodies[0]
    assert body["subdomain"] == "www"
    assert body["location"] == "https://example.org"
    assert body["type"] == "permanent"
    assert body["includePath"] == "yes"
    assert body["wildcard"] == "no"

    cmd = subprocess_spy[0]
    assert cmd[cmd.index("--action") + 1] == "URLFWD_ADD"
    assert cmd[cmd.index("--target") + 1] == "URLFWD `www` → https://example.org"


def test_add_url_forward_apex_uses_at_sign(
    fake_client: PorkbunClient, subprocess_spy: list[list[str]]
) -> None:
    fake_client._handlers.append(  # type: ignore[attr-defined]
        _match_path("/domain/addUrlForward/example.com", {"status": "SUCCESS"})
    )

    domains.add_url_forward_impl(
        fake_client, "example.com",
        subdomain="", location="https://example.org",
        reason="apex redirect",
    )

    cmd = subprocess_spy[0]
    assert cmd[cmd.index("--target") + 1] == "URLFWD `@` → https://example.org"


def test_delete_url_forward_emits_audit(
    fake_client: PorkbunClient, subprocess_spy: list[list[str]]
) -> None:
    fake_client._handlers.append(  # type: ignore[attr-defined]
        _match_path("/domain/deleteUrlForward/example.com/77", {"status": "SUCCESS"})
    )

    domains.delete_url_forward_impl(
        fake_client, "example.com", record_id="77",
        reason="Cleanup",
    )

    cmd = subprocess_spy[0]
    assert cmd[cmd.index("--action") + 1] == "URLFWD_DELETE"
    assert "--target" not in cmd
    payload = json.loads(cmd[cmd.index("--payload") + 1])
    assert payload == {"record_id": "77"}


# --- Labels ----------------------------------------------------------------


def test_add_label_emits_audit_and_returns_id(
    fake_client: PorkbunClient, subprocess_spy: list[list[str]]
) -> None:
    fake_client._handlers.append(  # type: ignore[attr-defined]
        _match_path(
            "/domain/labels/add/example.com",
            {"status": "SUCCESS", "id": 99},
        )
    )

    out = domains.add_label_impl(
        fake_client, "example.com",
        label_name="production", color="orange",
        reason="Tagging fleet",
    )

    assert out["id"] == 99
    cmd = subprocess_spy[0]
    assert cmd[cmd.index("--action") + 1] == "LABEL_ADD"
    assert cmd[cmd.index("--target") + 1] == "LABEL `production`"
    payload = json.loads(cmd[cmd.index("--payload") + 1])
    assert payload["color"] == "orange"
    assert payload["label_id"] == 99


def test_remove_label_emits_audit(
    fake_client: PorkbunClient, subprocess_spy: list[list[str]]
) -> None:
    fake_client._handlers.append(  # type: ignore[attr-defined]
        _match_path("/domain/labels/remove/example.com/99", {"status": "SUCCESS"})
    )

    domains.remove_label_impl(
        fake_client, "example.com", label_id="99",
        reason="Cleanup",
    )

    cmd = subprocess_spy[0]
    assert cmd[cmd.index("--action") + 1] == "LABEL_DELETE"
    assert "--target" not in cmd


# --- Cross-cutting ---------------------------------------------------------


def test_registrar_mutation_audit_disabled_skips_emit(
    fake_client: PorkbunClient, subprocess_spy: list[list[str]]
) -> None:
    fake_client._handlers.append(  # type: ignore[attr-defined]
        _match_path("/domain/createGlue/example.com/ns1", {"status": "SUCCESS"})
    )

    domains.create_glue_impl(
        fake_client, "example.com",
        host="ns1", ips=["1.1.1.1"],
        reason="r",
        audit_enabled=False,
    )
    assert subprocess_spy == []


def test_registrar_mutation_api_error_skips_audit(
    fake_client: PorkbunClient, subprocess_spy: list[list[str]]
) -> None:
    fake_client._handlers.append(  # type: ignore[attr-defined]
        lambda r: httpx.Response(
            400, json={"status": "ERROR", "message": "Bad host"},
        )
        if "/domain/createGlue/example.com/bad" in r.url.path else None
    )

    with pytest.raises(PorkbunAPIError):
        domains.create_glue_impl(
            fake_client, "example.com",
            host="bad", ips=["1.1.1.1"],
            reason="r",
        )
    assert subprocess_spy == []
