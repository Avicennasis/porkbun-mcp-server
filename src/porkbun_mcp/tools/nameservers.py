"""Nameserver tools: get (Phase 1), update (Phase 3 — mutation)."""

from __future__ import annotations

from typing import Any

from .. import audit as _audit
from ..client import PorkbunClient


def get_name_servers_impl(client: PorkbunClient, domain: str) -> dict[str, Any]:
    return client.post(f"/domain/getNs/{domain}")


def update_name_servers_impl(
    client: PorkbunClient,
    domain: str,
    *,
    ns: list[str],
    reason: str,
    audit_enabled: bool = True,
) -> dict[str, Any]:
    """Replace ``domain``'s nameservers. ``ns`` is the new list of NS
    hostnames (typically 2-4). ``reason`` is required.

    Audit row uses ``action=NS`` with no target column; the new NS list
    is captured in the payload column for searchability."""
    out = client.post(f"/domain/updateNs/{domain}", body={"ns": ns})
    _audit.emit_dns_change(
        action="NS",
        domain=domain,
        record_type=None,
        record_name="",
        reason=reason,
        new_ns=ns,
        enabled=audit_enabled,
    )
    return out
