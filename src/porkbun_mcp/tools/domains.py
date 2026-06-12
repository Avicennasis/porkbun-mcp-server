"""Domain-level tools: inventory (read), URL forwarding, glue records, labels.

Phase 1: 3 reads (list_domains, get_url_forwarding, list_labels).
Phase 4: 7 mutations — 3 glue, 2 URL forwarding, 2 labels. All emit
``category=domain`` audit rows via :func:`audit.emit_domain_change`.
"""

from __future__ import annotations

from typing import Any

from .. import audit as _audit
from ..client import PorkbunClient


def list_domains_impl(
    client: PorkbunClient,
    start: int = 0,
    include_labels: bool = False,
) -> dict[str, Any]:
    body: dict[str, Any] = {"start": start}
    if include_labels:
        body["includeLabels"] = "yes"
    return client.post("/domain/listAll", body=body)


def get_url_forwarding_impl(client: PorkbunClient, domain: str) -> dict[str, Any]:
    return client.post(f"/domain/getUrlForwarding/{domain}")


def list_labels_impl(client: PorkbunClient) -> dict[str, Any]:
    return client.post("/domain/labels/list")


def get_domain_impl(client: PorkbunClient, domain: str) -> dict[str, Any]:
    return client.post(f"/domain/get/{domain}")


def get_glue_impl(client: PorkbunClient, domain: str) -> dict[str, Any]:
    return client.post(f"/domain/getGlue/{domain}")


# ---------------------------------------------------------------------------
# Domain registration / renewal / transfer
# ---------------------------------------------------------------------------


def register_domain_impl(
    client: PorkbunClient,
    domain: str,
    *,
    cost: int,
    agree_to_terms: str = "yes",
    reason: str,
    audit_enabled: bool = True,
) -> dict[str, Any]:
    """Register a domain. ``cost`` is in pennies (USD cents) and must
    exactly match the price from ``check_availability``.
    ``agree_to_terms`` must be ``'yes'`` or ``'1'``."""
    body: dict[str, Any] = {"cost": cost, "agreeToTerms": agree_to_terms}
    out = client.post(f"/domain/create/{domain}", body=body)
    _audit.emit_domain_change(
        action="REGISTER",
        domain=domain,
        target=None,
        reason=reason,
        cost=cost,
        enabled=audit_enabled,
    )
    return out


def renew_domain_impl(
    client: PorkbunClient,
    domain: str,
    *,
    cost: int,
    reason: str,
    audit_enabled: bool = True,
) -> dict[str, Any]:
    """Renew a domain. ``cost`` is in pennies (USD cents) and must
    exactly match the renewal price from ``check_availability``."""
    body: dict[str, Any] = {"cost": cost}
    out = client.post(f"/domain/renew/{domain}", body=body)
    _audit.emit_domain_change(
        action="RENEW",
        domain=domain,
        target=None,
        reason=reason,
        cost=cost,
        enabled=audit_enabled,
    )
    return out


def transfer_domain_impl(
    client: PorkbunClient,
    domain: str,
    *,
    auth_code: str,
    cost: int,
    reason: str,
    audit_enabled: bool = True,
) -> dict[str, Any]:
    """Initiate an inbound domain transfer. ``auth_code`` is the EPP
    authorization code. ``cost`` is in pennies and must match the
    transfer price."""
    body: dict[str, Any] = {"authCode": auth_code, "cost": cost}
    out = client.post(f"/domain/transfer/{domain}", body=body)
    _audit.emit_domain_change(
        action="TRANSFER",
        domain=domain,
        target=None,
        reason=reason,
        cost=cost,
        enabled=audit_enabled,
    )
    return out


def get_transfer_status_impl(client: PorkbunClient, domain: str) -> dict[str, Any]:
    return client.post(f"/domain/getTransfer/{domain}")


def list_transfers_impl(client: PorkbunClient) -> dict[str, Any]:
    return client.post("/domain/listTransfers")


# ---------------------------------------------------------------------------
# Domain settings mutations
# ---------------------------------------------------------------------------


def update_auto_renew_impl(
    client: PorkbunClient,
    domain: str,
    *,
    auto_renew: bool,
    reason: str,
    audit_enabled: bool = True,
) -> dict[str, Any]:
    """Toggle auto-renewal for ``domain``. Porkbun expects the body key
    ``autoRenew`` as ``1`` (enable) or ``0`` (disable)."""
    body = {"autoRenew": 1 if auto_renew else 0}
    out = client.post(f"/domain/updateAutoRenew/{domain}", body=body)
    _audit.emit_domain_change(
        action="AUTO_RENEW",
        domain=domain,
        target=None,
        reason=reason,
        auto_renew=auto_renew,
        enabled=audit_enabled,
    )
    return out


# ---------------------------------------------------------------------------
# Glue record mutations (Phase 4)
# ---------------------------------------------------------------------------


def create_glue_impl(
    client: PorkbunClient,
    domain: str,
    *,
    host: str,
    ips: list[str],
    reason: str,
    audit_enabled: bool = True,
) -> dict[str, Any]:
    """Create a glue record (host A/AAAA records served by the registrar).
    Required when running custom nameservers like ``ns1.example.com`` that
    point at IPs you control."""
    out = client.post(f"/domain/createGlue/{domain}/{host}", body={"ips": ips})
    _audit.emit_domain_change(
        action="GLUE_CREATE",
        domain=domain,
        target=f"GLUE `{host}`",
        reason=reason,
        ips=ips,
        enabled=audit_enabled,
    )
    return out


def update_glue_impl(
    client: PorkbunClient,
    domain: str,
    *,
    host: str,
    ips: list[str],
    reason: str,
    audit_enabled: bool = True,
) -> dict[str, Any]:
    """Replace the IPs on an existing glue record."""
    out = client.post(f"/domain/updateGlue/{domain}/{host}", body={"ips": ips})
    _audit.emit_domain_change(
        action="GLUE_UPDATE",
        domain=domain,
        target=f"GLUE `{host}`",
        reason=reason,
        ips=ips,
        enabled=audit_enabled,
    )
    return out


def delete_glue_impl(
    client: PorkbunClient,
    domain: str,
    *,
    host: str,
    reason: str,
    audit_enabled: bool = True,
) -> dict[str, Any]:
    """Remove a glue record by host name."""
    out = client.post(f"/domain/deleteGlue/{domain}/{host}")
    _audit.emit_domain_change(
        action="GLUE_DELETE",
        domain=domain,
        target=f"GLUE `{host}`",
        reason=reason,
        enabled=audit_enabled,
    )
    return out


# ---------------------------------------------------------------------------
# URL forwarding mutations (Phase 4)
# ---------------------------------------------------------------------------


def add_url_forward_impl(
    client: PorkbunClient,
    domain: str,
    *,
    subdomain: str,
    location: str,
    type: str = "permanent",
    include_path: str = "no",
    wildcard: str = "no",
    reason: str,
    audit_enabled: bool = True,
) -> dict[str, Any]:
    """Add a URL forward. ``type`` is 'permanent' (301) or 'temporary' (302).
    ``include_path`` and ``wildcard`` are 'yes' / 'no' Porkbun-style flags.
    ``subdomain=""`` forwards the apex."""
    body = {
        "subdomain": subdomain,
        "location": location,
        "type": type,
        "includePath": include_path,
        "wildcard": wildcard,
    }
    out = client.post(f"/domain/addUrlForward/{domain}", body=body)
    name_disp = subdomain if subdomain else "@"
    _audit.emit_domain_change(
        action="URLFWD_ADD",
        domain=domain,
        target=f"URLFWD `{name_disp}` → {location}",
        reason=reason,
        type=type,
        include_path=include_path,
        wildcard=wildcard,
        enabled=audit_enabled,
    )
    return out


def delete_url_forward_impl(
    client: PorkbunClient,
    domain: str,
    record_id: str,
    *,
    reason: str,
    audit_enabled: bool = True,
) -> dict[str, Any]:
    """Remove a URL forward by record id (from ``get_url_forwarding``)."""
    out = client.post(f"/domain/deleteUrlForward/{domain}/{record_id}")
    _audit.emit_domain_change(
        action="URLFWD_DELETE",
        domain=domain,
        target=None,
        reason=reason,
        record_id=record_id,
        enabled=audit_enabled,
    )
    return out


# ---------------------------------------------------------------------------
# Label mutations (Phase 4)
# ---------------------------------------------------------------------------


def add_label_impl(
    client: PorkbunClient,
    domain: str,
    *,
    label_name: str,
    color: str,
    reason: str,
    audit_enabled: bool = True,
) -> dict[str, Any]:
    """Create a Porkbun label and attach it to ``domain``. ``color`` is a
    Porkbun-defined color name (``orange``, ``red``, ``blue``, ...)."""
    out = client.post(
        f"/domain/labels/add/{domain}",
        body={"title": label_name, "color": color},
    )
    _audit.emit_domain_change(
        action="LABEL_ADD",
        domain=domain,
        target=f"LABEL `{label_name}`",
        reason=reason,
        color=color,
        label_id=out.get("id"),
        enabled=audit_enabled,
    )
    return out


def remove_label_impl(
    client: PorkbunClient,
    domain: str,
    label_id: str,
    *,
    reason: str,
    audit_enabled: bool = True,
) -> dict[str, Any]:
    """Detach a label from ``domain`` by label id (from ``list_labels``)."""
    out = client.post(f"/domain/labels/remove/{domain}/{label_id}")
    _audit.emit_domain_change(
        action="LABEL_DELETE",
        domain=domain,
        target=None,
        reason=reason,
        label_id=label_id,
        enabled=audit_enabled,
    )
    return out
