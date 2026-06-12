"""DNS-record tools — 3 read + 6 mutation, each mutation emitting an
audit row via :mod:`porkbun_mcp.audit`.
"""

from __future__ import annotations

from typing import Any

from .. import audit as _audit
from ..client import PorkbunClient


def list_dns_records_impl(client: PorkbunClient, domain: str) -> dict[str, Any]:
    return client.post(f"/dns/retrieve/{domain}")


def get_dns_record_impl(client: PorkbunClient, domain: str, record_id: str) -> dict[str, Any]:
    return client.post(f"/dns/retrieve/{domain}/{record_id}")


def get_dns_records_by_name_type_impl(
    client: PorkbunClient, domain: str, type: str, subdomain: str = ""
) -> dict[str, Any]:
    path = f"/dns/retrieveByNameType/{domain}/{type}"
    if subdomain:
        path += f"/{subdomain}"
    return client.post(path)


# ---------------------------------------------------------------------------
# Mutations (Phase 2)
# ---------------------------------------------------------------------------


def _build_record_body(
    *,
    type: str | None,
    name: str | None,
    content: str,
    ttl: int = 600,
    prio: int | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Compose the JSON body Porkbun expects for record create/edit.

    ``type`` / ``name`` are omitted when the endpoint already encodes
    them in the URL (edit-by-name-type)."""
    body: dict[str, Any] = {"content": content, "ttl": str(ttl)}
    if type is not None:
        body["type"] = type.upper()
    if name is not None:
        body["name"] = name
    if prio is not None:
        body["prio"] = str(prio)
    if notes is not None:
        body["notes"] = notes
    return body


def create_dns_record_impl(
    client: PorkbunClient,
    domain: str,
    *,
    type: str,
    name: str,
    content: str,
    ttl: int = 600,
    prio: int | None = None,
    notes: str | None = None,
    reason: str,
    audit_enabled: bool = True,
) -> dict[str, Any]:
    """Create a DNS record on ``domain``.

    ``name`` is the subdomain ("" for apex). Porkbun accepts the body
    keys ``type`` / ``name`` / ``content`` / ``ttl`` / ``prio`` / ``notes``.
    On success Porkbun returns ``{"status": "SUCCESS", "id": <int>}``.
    """
    body = _build_record_body(
        type=type,
        name=name,
        content=content,
        ttl=ttl,
        prio=prio,
        notes=notes,
    )
    out = client.post(f"/dns/create/{domain}", body=body)
    _audit.emit_dns_change(
        action="POST",
        domain=domain,
        record_type=type.upper(),
        record_name=name,
        reason=reason,
        content=content,
        record_id=out.get("id"),
        enabled=audit_enabled,
    )
    return out


def edit_dns_record_impl(
    client: PorkbunClient,
    domain: str,
    record_id: str,
    *,
    type: str,
    name: str,
    content: str,
    ttl: int = 600,
    prio: int | None = None,
    notes: str | None = None,
    reason: str,
    audit_enabled: bool = True,
) -> dict[str, Any]:
    """Edit an existing DNS record by id. Porkbun's edit is a full
    replace — caller must pass every field. Body shape matches create.
    """
    body = _build_record_body(
        type=type,
        name=name,
        content=content,
        ttl=ttl,
        prio=prio,
        notes=notes,
    )
    out = client.post(f"/dns/edit/{domain}/{record_id}", body=body)
    _audit.emit_dns_change(
        action="PATCH",
        domain=domain,
        record_type=type.upper(),
        record_name=name,
        reason=reason,
        content=content,
        record_id=record_id,
        enabled=audit_enabled,
    )
    return out


def edit_dns_records_by_name_type_impl(
    client: PorkbunClient,
    domain: str,
    *,
    type: str,
    subdomain: str,
    content: str,
    ttl: int = 600,
    prio: int | None = None,
    notes: str | None = None,
    reason: str,
    audit_enabled: bool = True,
) -> dict[str, Any]:
    """Bulk-edit every record matching (type, subdomain) on ``domain``.

    ``subdomain="" → apex. Body must NOT include ``type`` / ``name``
    (already encoded in the URL path)."""
    body = _build_record_body(
        type=None,
        name=None,
        content=content,
        ttl=ttl,
        prio=prio,
        notes=notes,
    )
    path = f"/dns/editByNameType/{domain}/{type}"
    if subdomain:
        path += f"/{subdomain}"
    out = client.post(path, body=body)
    _audit.emit_dns_change(
        action="PATCH_BY_NAME_TYPE",
        domain=domain,
        record_type=type.upper(),
        record_name=subdomain,
        reason=reason,
        content=content,
        enabled=audit_enabled,
    )
    return out


def delete_dns_record_impl(
    client: PorkbunClient,
    domain: str,
    record_id: str,
    *,
    reason: str,
    audit_enabled: bool = True,
) -> dict[str, Any]:
    """Delete a DNS record by id. Type/name aren't recoverable from the
    URL — audit row omits the target column and stuffs ``record_id``
    in the payload."""
    out = client.post(f"/dns/delete/{domain}/{record_id}")
    _audit.emit_dns_change(
        action="DELETE",
        domain=domain,
        record_type=None,
        record_name="",
        reason=reason,
        record_id=record_id,
        enabled=audit_enabled,
    )
    return out


def delete_dns_records_by_name_type_impl(
    client: PorkbunClient,
    domain: str,
    *,
    type: str,
    subdomain: str,
    reason: str,
    audit_enabled: bool = True,
) -> dict[str, Any]:
    """Bulk-delete every record matching (type, subdomain) on ``domain``.

    ``subdomain="" → apex."""
    path = f"/dns/deleteByNameType/{domain}/{type}"
    if subdomain:
        path += f"/{subdomain}"
    out = client.post(path)
    _audit.emit_dns_change(
        action="DELETE_BY_NAME_TYPE",
        domain=domain,
        record_type=type.upper(),
        record_name=subdomain,
        reason=reason,
        enabled=audit_enabled,
    )
    return out


def bulk_create_dns_records_impl(
    client: PorkbunClient,
    domain: str,
    records: list[dict[str, Any]],
    *,
    reason: str,
    audit_enabled: bool = True,
) -> dict[str, Any]:
    """Continue-and-report bulk create. Porkbun has no native bulk
    endpoint — fan out one create per record. Each success emits its
    own POST audit row via :func:`create_dns_record_impl`; failures
    accumulate in ``failed`` and do NOT emit audit rows.

    Each entry in ``records`` must have ``type``, ``name``, ``content``;
    ``ttl`` / ``prio`` / ``notes`` are optional."""
    created: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    for entry in records:
        rec_type = entry.get("type")
        rec_name = entry.get("name")
        rec_content = entry.get("content")
        if not rec_type or rec_name is None or rec_content is None:
            failed.append(
                {"record": entry, "error": "missing required field (type, name, content)"}
            )
            continue
        try:
            result = create_dns_record_impl(
                client,
                domain,
                type=str(rec_type),
                name=str(rec_name),
                content=str(rec_content),
                ttl=int(entry.get("ttl", 600)),
                prio=entry.get("prio"),
                notes=entry.get("notes"),
                reason=reason,
                audit_enabled=audit_enabled,
            )
        except Exception as e:  # noqa: BLE001 — collect-and-report bulk wrapper
            failed.append({"record": entry, "error": str(e)})
            continue
        created.append(
            {
                "record_id": result.get("id"),
                "type": str(rec_type).upper(),
                "name": rec_name,
                "content": rec_content,
            }
        )

    return {
        "status": "SUCCESS" if not failed else "PARTIAL",
        "created": created,
        "failed": failed,
        "created_count": len(created),
        "failed_count": len(failed),
    }
