"""Account / meta tools: ping, pricing, balance, availability.

Each tool is a thin shim: the @mcp.tool() function calls the matching
``*_impl`` helper that takes an explicit ``PorkbunClient`` argument. The
split makes unit-testing trivial (pass a mock client) and keeps the
@mcp.tool() decorator on a function whose signature is exactly the user-
facing one.
"""

from __future__ import annotations

from typing import Any

from .. import pricing_cache
from ..client import PorkbunClient


def ping_impl(client: PorkbunClient) -> dict[str, Any]:
    """Authenticated ping; returns ``{"status": "SUCCESS", "yourIp": "<ip>"}``."""
    return client.post("/ping")


def get_pricing_impl(
    client: PorkbunClient, *, force_refresh: bool = False
) -> dict[str, Any]:
    """Public TLD pricing table — no auth required by Porkbun, but our
    client always sends auth, which is harmless here. Served through the
    disk TTL cache (see ``pricing_cache``); ``force_refresh=True``
    bypasses the cache and refetches."""
    return pricing_cache.get_pricing(client, force_refresh=force_refresh)


def get_account_balance_impl(client: PorkbunClient) -> dict[str, Any]:
    return client.post("/account/balance")


def check_availability_impl(client: PorkbunClient, domain: str) -> dict[str, Any]:
    return client.post(f"/domain/checkDomain/{domain}")


def check_bulk_availability_impl(
    client: PorkbunClient, domains: list[str]
) -> dict[str, Any]:
    """Client-side fan-out: Porkbun has no native bulk availability."""
    results: dict[str, Any] = {}
    for d in domains:
        try:
            results[d] = client.post(f"/domain/checkDomain/{d}")
        except Exception as e:  # noqa: BLE001 — surface per-domain failures
            results[d] = {"status": "ERROR", "message": str(e)}
    return {"status": "SUCCESS", "results": results}


def get_pricing_for_tld_impl(
    client: PorkbunClient, tld: str, *, force_refresh: bool = False
) -> dict[str, Any]:
    """Extract one TLD's pricing from the full (cached) pricing response."""
    full = get_pricing_impl(client, force_refresh=force_refresh)
    pricing = full.get("pricing", {}).get(tld)
    if pricing is None:
        return {"status": "ERROR", "message": f"TLD '{tld}' not in pricing table"}
    return {"status": "SUCCESS", "tld": tld, "pricing": pricing}


def list_supported_tlds_impl(
    client: PorkbunClient, *, force_refresh: bool = False
) -> dict[str, Any]:
    full = get_pricing_impl(client, force_refresh=force_refresh)
    return {"status": "SUCCESS", "tlds": sorted(full.get("pricing", {}).keys())}


def get_api_settings_impl(client: PorkbunClient) -> dict[str, Any]:
    return client.post("/account/apiSettings")


def get_ip_impl(client: PorkbunClient) -> dict[str, Any]:
    return client.post("/ip")


def create_invite_impl(
    client: PorkbunClient,
    *,
    email: str | None = None,
    return_url: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {}
    if email is not None:
        body["email"] = email
    if return_url is not None:
        body["returnUrl"] = return_url
    return client.post("/account/invite", body=body if body else None)


def get_invite_status_impl(
    client: PorkbunClient, token: str
) -> dict[str, Any]:
    return client.post("/account/inviteStatus", body={"token": token})


def set_email_password_impl(
    client: PorkbunClient,
    *,
    email_address: str,
    password: str,
) -> dict[str, Any]:
    return client.post(
        "/email/setPassword",
        body={"emailAddress": email_address, "password": password},
    )


def request_api_key_impl(
    client: PorkbunClient, *, name: str | None = None
) -> dict[str, Any]:
    body: dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    return client.post("/apikey/request", body=body if body else None)


def retrieve_api_key_impl(
    client: PorkbunClient, *, request_token: str
) -> dict[str, Any]:
    return client.post("/apikey/retrieve", body={"requestToken": request_token})
