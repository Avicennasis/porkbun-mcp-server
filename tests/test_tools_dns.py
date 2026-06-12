"""dns.py tool tests."""

from __future__ import annotations

import json

import httpx
import pytest

from porkbun_mcp.client import PorkbunClient
from porkbun_mcp.errors import PorkbunAPIError
from porkbun_mcp.tools import dns

# ---------------------------------------------------------------------------
# Read tools (Phase 1)
# ---------------------------------------------------------------------------


def test_list_dns_records(fake_client: PorkbunClient) -> None:
    fake_client._handlers.append(  # type: ignore[attr-defined]
        lambda r: (
            httpx.Response(
                200,
                json={
                    "status": "SUCCESS",
                    "records": [
                        {
                            "id": "1",
                            "type": "A",
                            "name": "test.example.com",
                            "content": "1.2.3.4",
                            "ttl": "600",
                        },
                        {
                            "id": "2",
                            "type": "MX",
                            "name": "example.com",
                            "content": "mail.example.com",
                            "prio": "10",
                        },
                    ],
                },
            )
            if r.url.path.endswith("/dns/retrieve/example.com")
            else None
        )
    )
    out = dns.list_dns_records_impl(fake_client, "example.com")
    assert len(out["records"]) == 2


def test_get_dns_record(fake_client: PorkbunClient) -> None:
    fake_client._handlers.append(  # type: ignore[attr-defined]
        lambda r: (
            httpx.Response(
                200,
                json={
                    "status": "SUCCESS",
                    "records": [
                        {"id": "42", "type": "A", "name": "x.example.com", "content": "1.1.1.1"}
                    ],
                },
            )
            if r.url.path.endswith("/dns/retrieve/example.com/42")
            else None
        )
    )
    out = dns.get_dns_record_impl(fake_client, "example.com", "42")
    assert out["records"][0]["id"] == "42"


def test_get_dns_records_by_name_type(fake_client: PorkbunClient) -> None:
    fake_client._handlers.append(  # type: ignore[attr-defined]
        lambda r: (
            httpx.Response(
                200,
                json={
                    "status": "SUCCESS",
                    "records": [{"id": "10", "type": "TXT", "name": "_acme-challenge.example.com"}],
                },
            )
            if "/dns/retrieveByNameType/example.com/TXT/_acme-challenge" in r.url.path
            else None
        )
    )
    out = dns.get_dns_records_by_name_type_impl(
        fake_client, "example.com", "TXT", "_acme-challenge"
    )
    assert out["records"][0]["type"] == "TXT"


def test_get_dns_records_by_name_type_no_subdomain(fake_client: PorkbunClient) -> None:
    """Empty subdomain → apex query, path drops the trailing slash."""
    captured: list = []

    def handler(r: httpx.Request) -> httpx.Response | None:
        captured.append(r.url.path)
        if "/dns/retrieveByNameType/example.com/A" in r.url.path:
            return httpx.Response(200, json={"status": "SUCCESS", "records": []})
        return None

    fake_client._handlers.append(handler)  # type: ignore[attr-defined]
    dns.get_dns_records_by_name_type_impl(fake_client, "example.com", "A", "")
    assert captured[0].endswith("/dns/retrieveByNameType/example.com/A")


# ---------------------------------------------------------------------------
# Mutation tools (Phase 2)
# ---------------------------------------------------------------------------


def _match_path(suffix: str, response_json: dict):
    """Build a handler returning ``response_json`` only for the given path suffix."""

    def handler(r: httpx.Request) -> httpx.Response | None:
        if r.url.path.endswith(suffix) or suffix in r.url.path:
            return httpx.Response(200, json=response_json)
        return None

    return handler


def _capture_request(suffix: str, response_json: dict):
    """Like ``_match_path`` but also captures the JSON body for assertions."""
    captured: list[dict] = []

    def handler(r: httpx.Request) -> httpx.Response | None:
        if suffix in r.url.path:
            captured.append(json.loads(r.content.decode()))
            return httpx.Response(200, json=response_json)
        return None

    return handler, captured


def test_create_dns_record_calls_api_and_emits_audit(
    fake_client: PorkbunClient, subprocess_spy: list[list[str]]
) -> None:
    handler, bodies = _capture_request(
        "/dns/create/example.com",
        {"status": "SUCCESS", "id": 12345},
    )
    fake_client._handlers.append(handler)  # type: ignore[attr-defined]

    out = dns.create_dns_record_impl(
        fake_client,
        "example.com",
        type="A",
        name="vm-x",
        content="1.2.3.4",
        ttl=300,
        reason="Mesh node onboarding",
    )

    assert out["id"] == 12345
    assert bodies[0]["type"] == "A"
    assert bodies[0]["name"] == "vm-x"
    assert bodies[0]["content"] == "1.2.3.4"
    assert bodies[0]["ttl"] == "300"

    cmd = subprocess_spy[0]
    assert cmd[cmd.index("--action") + 1] == "POST"
    assert cmd[cmd.index("--service") + 1] == "example.com"
    assert cmd[cmd.index("--target") + 1] == "A `vm-x`"
    assert cmd[cmd.index("--reason") + 1] == "Mesh node onboarding"
    payload = json.loads(cmd[cmd.index("--payload") + 1])
    assert payload["content"] == "1.2.3.4"
    assert payload["record_id"] == 12345


def test_create_dns_record_apex_uses_at_sign_in_audit(
    fake_client: PorkbunClient, subprocess_spy: list[list[str]]
) -> None:
    fake_client._handlers.append(  # type: ignore[attr-defined]
        _match_path("/dns/create/example.com", {"status": "SUCCESS", "id": 1})
    )

    dns.create_dns_record_impl(
        fake_client,
        "example.com",
        type="A",
        name="",
        content="1.1.1.1",
        reason="apex",
    )

    cmd = subprocess_spy[0]
    assert cmd[cmd.index("--target") + 1] == "A `@`"


def test_edit_dns_record_calls_api_and_emits_audit(
    fake_client: PorkbunClient, subprocess_spy: list[list[str]]
) -> None:
    handler, bodies = _capture_request(
        "/dns/edit/example.com/42",
        {"status": "SUCCESS"},
    )
    fake_client._handlers.append(handler)  # type: ignore[attr-defined]

    dns.edit_dns_record_impl(
        fake_client,
        "example.com",
        "42",
        type="A",
        name="vm-x",
        content="5.6.7.8",
        ttl=600,
        prio=None,
        reason="IP rotation",
    )

    assert bodies[0]["content"] == "5.6.7.8"
    cmd = subprocess_spy[0]
    assert cmd[cmd.index("--action") + 1] == "PATCH"
    assert cmd[cmd.index("--target") + 1] == "A `vm-x`"
    payload = json.loads(cmd[cmd.index("--payload") + 1])
    assert payload["record_id"] == "42"


def test_edit_by_name_type_omits_type_name_from_body(
    fake_client: PorkbunClient, subprocess_spy: list[list[str]]
) -> None:
    handler, bodies = _capture_request(
        "/dns/editByNameType/example.com/A/vm-x",
        {"status": "SUCCESS"},
    )
    fake_client._handlers.append(handler)  # type: ignore[attr-defined]

    dns.edit_dns_records_by_name_type_impl(
        fake_client,
        "example.com",
        type="A",
        subdomain="vm-x",
        content="9.9.9.9",
        reason="bulk rotate",
    )

    assert "type" not in bodies[0]
    assert "name" not in bodies[0]
    assert bodies[0]["content"] == "9.9.9.9"
    cmd = subprocess_spy[0]
    assert cmd[cmd.index("--action") + 1] == "PATCH_BY_NAME_TYPE"
    assert cmd[cmd.index("--target") + 1] == "A `vm-x`"


def test_edit_by_name_type_apex(
    fake_client: PorkbunClient, subprocess_spy: list[list[str]]
) -> None:
    """Empty subdomain → path drops the trailing /, target uses @."""
    captured_path: list[str] = []

    def handler(r: httpx.Request) -> httpx.Response | None:
        captured_path.append(r.url.path)
        if "/dns/editByNameType/example.com/A" in r.url.path:
            return httpx.Response(200, json={"status": "SUCCESS"})
        return None

    fake_client._handlers.append(handler)  # type: ignore[attr-defined]
    dns.edit_dns_records_by_name_type_impl(
        fake_client,
        "example.com",
        type="A",
        subdomain="",
        content="1.1.1.1",
        reason="r",
    )
    assert captured_path[0].endswith("/dns/editByNameType/example.com/A")
    cmd = subprocess_spy[0]
    assert cmd[cmd.index("--target") + 1] == "A `@`"


def test_delete_dns_record_omits_target_and_records_id(
    fake_client: PorkbunClient, subprocess_spy: list[list[str]]
) -> None:
    fake_client._handlers.append(  # type: ignore[attr-defined]
        _match_path("/dns/delete/example.com/42", {"status": "SUCCESS"})
    )

    dns.delete_dns_record_impl(
        fake_client,
        "example.com",
        "42",
        reason="Stale ACME challenge",
    )

    cmd = subprocess_spy[0]
    assert cmd[cmd.index("--action") + 1] == "DELETE"
    assert "--target" not in cmd
    payload = json.loads(cmd[cmd.index("--payload") + 1])
    assert payload == {"record_id": "42"}


def test_delete_by_name_type_keeps_target(
    fake_client: PorkbunClient, subprocess_spy: list[list[str]]
) -> None:
    fake_client._handlers.append(  # type: ignore[attr-defined]
        _match_path(
            "/dns/deleteByNameType/example.com/TXT/_acme-challenge",
            {"status": "SUCCESS"},
        )
    )

    dns.delete_dns_records_by_name_type_impl(
        fake_client,
        "example.com",
        type="TXT",
        subdomain="_acme-challenge",
        reason="cleanup",
    )

    cmd = subprocess_spy[0]
    assert cmd[cmd.index("--action") + 1] == "DELETE_BY_NAME_TYPE"
    assert cmd[cmd.index("--target") + 1] == "TXT `_acme-challenge`"


def test_bulk_create_fans_out_to_per_record_creates(
    fake_client: PorkbunClient, subprocess_spy: list[list[str]]
) -> None:
    fake_client._handlers.append(  # type: ignore[attr-defined]
        _match_path("/dns/create/example.com", {"status": "SUCCESS", "id": 7})
    )

    out = dns.bulk_create_dns_records_impl(
        fake_client,
        "example.com",
        records=[
            {"type": "A", "name": "a", "content": "1.1.1.1"},
            {"type": "A", "name": "b", "content": "2.2.2.2"},
        ],
        reason="bulk import",
    )

    assert out["status"] == "SUCCESS"
    assert out["created_count"] == 2
    assert out["failed_count"] == 0
    # Two POST audit rows, one per record
    assert len(subprocess_spy) == 2
    assert all(cmd[cmd.index("--action") + 1] == "POST" for cmd in subprocess_spy)


def test_bulk_create_partial_on_missing_fields(
    fake_client: PorkbunClient, subprocess_spy: list[list[str]]
) -> None:
    fake_client._handlers.append(  # type: ignore[attr-defined]
        _match_path("/dns/create/example.com", {"status": "SUCCESS", "id": 1})
    )

    out = dns.bulk_create_dns_records_impl(
        fake_client,
        "example.com",
        records=[
            {"type": "A", "name": "a", "content": "1.1.1.1"},
            {"type": "A", "name": "b"},  # missing content
        ],
        reason="partial",
    )

    assert out["status"] == "PARTIAL"
    assert out["created_count"] == 1
    assert out["failed_count"] == 1
    assert "content" in out["failed"][0]["error"]
    # Only one audit row — the missing-field failure never reached the API
    assert len(subprocess_spy) == 1


def test_audit_disabled_skips_emit(
    fake_client: PorkbunClient, subprocess_spy: list[list[str]]
) -> None:
    fake_client._handlers.append(  # type: ignore[attr-defined]
        _match_path("/dns/create/example.com", {"status": "SUCCESS", "id": 1})
    )

    dns.create_dns_record_impl(
        fake_client,
        "example.com",
        type="A",
        name="x",
        content="1.1.1.1",
        reason="r",
        audit_enabled=False,
    )
    assert subprocess_spy == []


def test_api_error_skips_audit_emit(
    fake_client: PorkbunClient, subprocess_spy: list[list[str]]
) -> None:
    """When Porkbun returns status:ERROR, the client raises and the
    audit emit line never executes."""
    fake_client._handlers.append(  # type: ignore[attr-defined]
        lambda r: (
            httpx.Response(
                400,
                json={"status": "ERROR", "message": "Bad type"},
            )
            if "/dns/create/example.com" in r.url.path
            else None
        )
    )

    with pytest.raises(PorkbunAPIError):
        dns.create_dns_record_impl(
            fake_client,
            "example.com",
            type="BOGUS",
            name="x",
            content="y",
            reason="r",
        )
    assert subprocess_spy == []
