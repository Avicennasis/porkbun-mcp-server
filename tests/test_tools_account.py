"""account.py tool tests."""

from __future__ import annotations

import httpx

from porkbun_mcp.client import PorkbunClient
from porkbun_mcp.tools import account


def test_ping_returns_ip(fake_client: PorkbunClient) -> None:
    fake_client._handlers.append(  # type: ignore[attr-defined]
        lambda r: (
            httpx.Response(200, json={"status": "SUCCESS", "yourIp": "1.2.3.4"})
            if r.url.path.endswith("/ping")
            else None
        )
    )
    out = account.ping_impl(fake_client)
    assert out["status"] == "SUCCESS"
    assert out["yourIp"] == "1.2.3.4"


def test_get_pricing_returns_pricing_table(fake_client: PorkbunClient) -> None:
    fake_client._handlers.append(  # type: ignore[attr-defined]
        lambda r: (
            httpx.Response(
                200,
                json={
                    "status": "SUCCESS",
                    "pricing": {
                        "com": {"registration": "9.13", "renewal": "9.13", "transfer": "9.13"},
                        "net": {"registration": "11.32", "renewal": "11.32", "transfer": "11.32"},
                    },
                },
            )
            if r.url.path.endswith("/pricing/get")
            else None
        )
    )
    out = account.get_pricing_impl(fake_client)
    assert out["pricing"]["com"]["registration"] == "9.13"


def test_get_account_balance(fake_client: PorkbunClient) -> None:
    fake_client._handlers.append(  # type: ignore[attr-defined]
        lambda r: (
            httpx.Response(200, json={"status": "SUCCESS", "balance": "27.42"})
            if r.url.path.endswith("/account/balance")
            else None
        )
    )
    out = account.get_account_balance_impl(fake_client)
    assert out["balance"] == "27.42"


def test_check_availability_taken(fake_client: PorkbunClient) -> None:
    fake_client._handlers.append(  # type: ignore[attr-defined]
        lambda r: (
            httpx.Response(
                200, json={"status": "SUCCESS", "response": {"avail": "no", "type": "registered"}}
            )
            if "/domain/checkDomain/" in r.url.path
            else None
        )
    )
    out = account.check_availability_impl(fake_client, "example.com")
    assert out["response"]["avail"] == "no"


def test_check_bulk_availability(fake_client: PorkbunClient) -> None:
    """Client-side fan-out: one Porkbun call per domain."""
    calls: list[str] = []

    def handler(r: httpx.Request) -> httpx.Response | None:
        if "/domain/checkDomain/" in r.url.path:
            calls.append(r.url.path)
            domain = r.url.path.rsplit("/", 1)[-1]
            avail = "yes" if domain == "free.com" else "no"
            return httpx.Response(200, json={"status": "SUCCESS", "response": {"avail": avail}})
        return None

    fake_client._handlers.append(handler)  # type: ignore[attr-defined]

    out = account.check_bulk_availability_impl(fake_client, ["taken.com", "free.com"])
    assert len(out["results"]) == 2
    assert out["results"]["free.com"]["response"]["avail"] == "yes"
    assert out["results"]["taken.com"]["response"]["avail"] == "no"
    assert len(calls) == 2


def test_get_pricing_for_tld_extracts_subset(fake_client: PorkbunClient) -> None:
    fake_client._handlers.append(  # type: ignore[attr-defined]
        lambda r: (
            httpx.Response(
                200,
                json={
                    "status": "SUCCESS",
                    "pricing": {
                        "com": {"registration": "9.13", "renewal": "9.13"},
                        "net": {"registration": "11.32"},
                    },
                },
            )
            if r.url.path.endswith("/pricing/get")
            else None
        )
    )
    out = account.get_pricing_for_tld_impl(fake_client, "com")
    assert out["tld"] == "com"
    assert out["pricing"]["registration"] == "9.13"


def test_get_pricing_for_tld_unknown_returns_error(fake_client: PorkbunClient) -> None:
    fake_client._handlers.append(  # type: ignore[attr-defined]
        lambda r: (
            httpx.Response(200, json={"status": "SUCCESS", "pricing": {"com": {}}})
            if r.url.path.endswith("/pricing/get")
            else None
        )
    )
    out = account.get_pricing_for_tld_impl(fake_client, "bogus")
    assert out["status"] == "ERROR"


def test_list_supported_tlds(fake_client: PorkbunClient) -> None:
    fake_client._handlers.append(  # type: ignore[attr-defined]
        lambda r: (
            httpx.Response(
                200,
                json={
                    "status": "SUCCESS",
                    "pricing": {"com": {"registration": "9.13"}, "net": {}, "org": {}},
                },
            )
            if r.url.path.endswith("/pricing/get")
            else None
        )
    )
    out = account.list_supported_tlds_impl(fake_client)
    assert sorted(out["tlds"]) == ["com", "net", "org"]


def test_get_api_settings(fake_client: PorkbunClient) -> None:
    fake_client._handlers.append(  # type: ignore[attr-defined]
        lambda r: (
            httpx.Response(
                200,
                json={
                    "status": "SUCCESS",
                    "settings": {"monthlySpendLimit": 10000, "currentMonthSpend": 913},
                },
            )
            if r.url.path.endswith("/account/apiSettings")
            else None
        )
    )
    out = account.get_api_settings_impl(fake_client)
    assert out["settings"]["monthlySpendLimit"] == 10000


def test_get_ip(fake_client: PorkbunClient) -> None:
    fake_client._handlers.append(  # type: ignore[attr-defined]
        lambda r: (
            httpx.Response(200, json={"status": "SUCCESS", "yourIp": "203.0.113.42"})
            if r.url.path.endswith("/ip")
            else None
        )
    )
    out = account.get_ip_impl(fake_client)
    assert out["yourIp"] == "203.0.113.42"


def test_create_invite(fake_client: PorkbunClient) -> None:
    captured: list = []

    def handler(r: httpx.Request) -> httpx.Response | None:
        if r.url.path.endswith("/account/invite"):
            import json as _json

            captured.append(_json.loads(r.content))
            return httpx.Response(
                200, json={"status": "SUCCESS", "inviteToken": "abc123", "authUrl": "https://..."}
            )
        return None

    fake_client._handlers.append(handler)  # type: ignore[attr-defined]
    out = account.create_invite_impl(
        fake_client, email="user@test.com", return_url="https://app.com/done"
    )
    assert out["inviteToken"] == "abc123"
    assert captured[0]["email"] == "user@test.com"
    assert captured[0]["returnUrl"] == "https://app.com/done"


def test_get_invite_status(fake_client: PorkbunClient) -> None:
    fake_client._handlers.append(  # type: ignore[attr-defined]
        lambda r: (
            httpx.Response(
                200, json={"status": "SUCCESS", "inviteStatus": "ACCEPTED", "newAccountId": 42}
            )
            if r.url.path.endswith("/account/inviteStatus")
            else None
        )
    )
    out = account.get_invite_status_impl(fake_client, "abc123")
    assert out["inviteStatus"] == "ACCEPTED"


def test_set_email_password(fake_client: PorkbunClient) -> None:
    captured: list = []

    def handler(r: httpx.Request) -> httpx.Response | None:
        if r.url.path.endswith("/email/setPassword"):
            import json as _json

            captured.append(_json.loads(r.content))
            return httpx.Response(200, json={"status": "SUCCESS"})
        return None

    fake_client._handlers.append(handler)  # type: ignore[attr-defined]
    out = account.set_email_password_impl(
        fake_client, email_address="me@example.com", password="s3cr3t!"
    )
    assert out["status"] == "SUCCESS"
    assert captured[0]["emailAddress"] == "me@example.com"
    assert captured[0]["password"] == "s3cr3t!"


def test_request_api_key(fake_client: PorkbunClient) -> None:
    fake_client._handlers.append(  # type: ignore[attr-defined]
        lambda r: (
            httpx.Response(
                200,
                json={
                    "status": "SUCCESS",
                    "requestToken": "deadbeef" * 8,
                    "authUrl": "https://...",
                },
            )
            if r.url.path.endswith("/apikey/request")
            else None
        )
    )
    out = account.request_api_key_impl(fake_client, name="My App")
    assert out["requestToken"] == "deadbeef" * 8


def test_retrieve_api_key(fake_client: PorkbunClient) -> None:
    fake_client._handlers.append(  # type: ignore[attr-defined]
        lambda r: (
            httpx.Response(200, json={"status": "SUCCESS", "apikey": "pk1_abc123"})
            if r.url.path.endswith("/apikey/retrieve")
            else None
        )
    )
    out = account.retrieve_api_key_impl(fake_client, request_token="deadbeef" * 8)
    assert out["apikey"] == "pk1_abc123"
