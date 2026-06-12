"""dnssec.py tool tests — read (Phase 1) + mutations (Phase 3)."""

from __future__ import annotations

import json

import httpx
import pytest

from porkbun_mcp.client import PorkbunClient
from porkbun_mcp.errors import PorkbunAPIError
from porkbun_mcp.tools import dnssec


def test_get_dnssec_records(fake_client: PorkbunClient) -> None:
    fake_client._handlers.append(  # type: ignore[attr-defined]
        lambda r: httpx.Response(
            200,
            json={
                "status": "SUCCESS",
                "records": {
                    "12345": {
                        "keyTag": "12345",
                        "alg": "13",
                        "digestType": "2",
                        "digest": "abc...",
                    }
                },
            },
        )
        if "/dns/getDnssecRecords/" in r.url.path
        else None
    )
    out = dnssec.get_dnssec_records_impl(fake_client, "example.com")
    assert "12345" in out["records"]


# ---------------------------------------------------------------------------
# Mutations (Phase 3)
# ---------------------------------------------------------------------------


def _capture_request(suffix: str, response_json: dict):
    captured: list[dict] = []

    def handler(r: httpx.Request) -> httpx.Response | None:
        if suffix in r.url.path:
            captured.append(json.loads(r.content.decode()))
            return httpx.Response(200, json=response_json)
        return None

    return handler, captured


def test_create_dnssec_record_required_fields_only(
    fake_client: PorkbunClient, subprocess_spy: list[list[str]]
) -> None:
    handler, bodies = _capture_request(
        "/dns/createDnssecRecord/example.com",
        {"status": "SUCCESS"},
    )
    fake_client._handlers.append(handler)  # type: ignore[attr-defined]

    dnssec.create_dnssec_record_impl(
        fake_client, "example.com",
        key_tag="12345", alg="13", digest_type="2", digest="abcdef",
        reason="Enabling DNSSEC for zone",
    )

    body = bodies[0]
    assert body["keyTag"] == "12345"
    assert body["alg"] == "13"
    assert body["digestType"] == "2"
    assert body["digest"] == "abcdef"
    # Optional keyData_* fields omitted entirely when not provided
    assert "keyDataPubKey" not in body
    assert "maxSigLife" not in body

    cmd = subprocess_spy[0]
    assert cmd[cmd.index("--action") + 1] == "DNSSEC_ADD"
    assert cmd[cmd.index("--service") + 1] == "example.com"
    assert cmd[cmd.index("--target") + 1] == "DS `keytag=12345`"
    payload = json.loads(cmd[cmd.index("--payload") + 1])
    assert payload == {"alg": "13", "digest_type": "2"}


def test_create_dnssec_record_with_keydata(
    fake_client: PorkbunClient, subprocess_spy: list[list[str]]
) -> None:
    handler, bodies = _capture_request(
        "/dns/createDnssecRecord/example.com",
        {"status": "SUCCESS"},
    )
    fake_client._handlers.append(handler)  # type: ignore[attr-defined]

    dnssec.create_dnssec_record_impl(
        fake_client, "example.com",
        key_tag="12345", alg="13", digest_type="2", digest="abc",
        max_sig_life="3600",
        key_data_flags="257", key_data_protocol="3",
        key_data_algorithm="13", key_data_pub_key="<base64>",
        reason="DNSKEY-derived DS",
    )

    body = bodies[0]
    assert body["maxSigLife"] == "3600"
    assert body["keyDataFlags"] == "257"
    assert body["keyDataProtocol"] == "3"
    assert body["keyDataAlgorithm"] == "13"
    assert body["keyDataPubKey"] == "<base64>"


def test_delete_dnssec_record_path_includes_key_tag(
    fake_client: PorkbunClient, subprocess_spy: list[list[str]]
) -> None:
    captured_paths: list[str] = []

    def handler(r: httpx.Request) -> httpx.Response | None:
        captured_paths.append(r.url.path)
        if "/dns/deleteDnssecRecord/example.com/12345" in r.url.path:
            return httpx.Response(200, json={"status": "SUCCESS"})
        return None

    fake_client._handlers.append(handler)  # type: ignore[attr-defined]

    dnssec.delete_dnssec_record_impl(
        fake_client, "example.com",
        key_tag="12345",
        reason="Rotating KSK",
    )

    assert captured_paths[0].endswith("/dns/deleteDnssecRecord/example.com/12345")
    cmd = subprocess_spy[0]
    assert cmd[cmd.index("--action") + 1] == "DNSSEC_DELETE"
    assert cmd[cmd.index("--target") + 1] == "DS `keytag=12345`"


def test_dnssec_audit_disabled_skips_emit(
    fake_client: PorkbunClient, subprocess_spy: list[list[str]]
) -> None:
    fake_client._handlers.append(  # type: ignore[attr-defined]
        lambda r: httpx.Response(200, json={"status": "SUCCESS"})
        if "/dns/createDnssecRecord/example.com" in r.url.path else None
    )

    dnssec.create_dnssec_record_impl(
        fake_client, "example.com",
        key_tag="1", alg="13", digest_type="2", digest="x",
        reason="r",
        audit_enabled=False,
    )
    assert subprocess_spy == []


def test_dnssec_api_error_skips_audit(
    fake_client: PorkbunClient, subprocess_spy: list[list[str]]
) -> None:
    fake_client._handlers.append(  # type: ignore[attr-defined]
        lambda r: httpx.Response(
            400, json={"status": "ERROR", "message": "Bad alg"},
        )
        if "/dns/createDnssecRecord/example.com" in r.url.path else None
    )

    with pytest.raises(PorkbunAPIError):
        dnssec.create_dnssec_record_impl(
            fake_client, "example.com",
            key_tag="1", alg="999", digest_type="2", digest="x",
            reason="r",
        )
    assert subprocess_spy == []
