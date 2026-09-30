"""The first real approval kinds: DNS records (#50877).

`approval_surface.py` defines a handler as `kind -> (apply, revert)`. This is
where a kind gets an actual provider call, and it is the half that makes the
journal more than bookkeeping.

## The thing that decides whether this is safe

**A revert must be able to run without anything but the record.** The poller may
resolve an approval hours after it was submitted, from a process that restarted
in between, so a revert that needs information nobody wrote down is a revert
that cannot run — which would make `deny` a lie.

So each payload carries what its inverse needs:

- `dns.create` — the create returns a record id, and `apply` **writes it back
  into the payload** so the revert knows what to delete. The journal persists
  after `apply`, so that survives a restart.
- `dns.delete` — the inverse is a *re*-create, so the payload must carry the
  record's full contents. A delete submitted without them cannot be reverted,
  and the apply refuses rather than removing something it cannot put back.

That second rule is the important one. A one-way delete that reports itself as
revertible is worse than one that admits it is not.
"""

from __future__ import annotations

from typing import Any

from porkbun_mcp.approval import ActionRecord
from porkbun_mcp.approval_surface import Handler
from porkbun_mcp.client import PorkbunClient
from porkbun_mcp.tools import dns

#: Kinds this module can apply. Named `<area>.<verb>` to match the engine's
#: `kind` field, and deliberately explicit rather than derived from tool names —
#: a tool renamed upstream must not silently change what an approval means.
KIND_CREATE = "dns.create"
KIND_DELETE = "dns.delete"


class UnrevertibleError(RuntimeError):
    """A delete that cannot be put back, because its contents were not captured."""


def _apply_create(client: PorkbunClient, record: ActionRecord, *, audit_enabled: bool) -> None:
    payload = record.payload
    out = dns.create_dns_record_impl(
        client,
        payload["domain"],
        type=payload["type"],
        name=payload.get("name", ""),
        content=payload["content"],
        ttl=int(payload.get("ttl", 600)),
        prio=payload.get("prio"),
        notes=payload.get("notes"),
        reason=payload.get("reason", f"approved action #{record.id}"),
        audit_enabled=audit_enabled,
    )
    # The revert's whole input. Written back so it survives a poller restart:
    # `journal.apply` persists the record after this returns.
    record.payload["created_record_id"] = out.get("id")


def _revert_create(client: PorkbunClient, record: ActionRecord, *, audit_enabled: bool) -> None:
    record_id = record.payload.get("created_record_id")
    if not record_id:
        # The apply never completed, so there is nothing at the provider to undo.
        # That is a success for a revert, not a failure.
        return
    dns.delete_dns_record_impl(
        client,
        record.payload["domain"],
        str(record_id),
        reason=f"revert of approved action #{record.id}",
        audit_enabled=audit_enabled,
    )


def _apply_delete(client: PorkbunClient, record: ActionRecord, *, audit_enabled: bool) -> None:
    payload = record.payload
    if not payload.get("record"):
        # Refuse BEFORE the call. Deleting and only then discovering we cannot
        # put it back is the one ordering that loses data.
        raise UnrevertibleError(
            f"action #{record.id} would delete {payload.get('record_id')} without capturing the "
            f"record's contents; submit a payload with 'record' so the delete is revertible"
        )
    dns.delete_dns_record_impl(
        client,
        payload["domain"],
        str(payload["record_id"]),
        reason=payload.get("reason", f"approved action #{record.id}"),
        audit_enabled=audit_enabled,
    )


def _revert_delete(client: PorkbunClient, record: ActionRecord, *, audit_enabled: bool) -> None:
    captured: dict[str, Any] = record.payload["record"]
    dns.create_dns_record_impl(
        client,
        record.payload["domain"],
        type=captured["type"],
        name=captured.get("name", ""),
        content=captured["content"],
        ttl=int(captured.get("ttl", 600)),
        prio=captured.get("prio"),
        notes=captured.get("notes"),
        reason=f"revert of approved action #{record.id}",
        audit_enabled=audit_enabled,
    )


def build_handlers(client: PorkbunClient, *, audit_enabled: bool = True) -> dict[str, Handler]:
    """The registry the poller uses. Passed a client rather than building one, so
    it is testable without credentials."""

    def create_pair() -> Handler:
        return (
            lambda r: _apply_create(client, r, audit_enabled=audit_enabled),
            lambda r: _revert_create(client, r, audit_enabled=audit_enabled),
        )

    def delete_pair() -> Handler:
        return (
            lambda r: _apply_delete(client, r, audit_enabled=audit_enabled),
            lambda r: _revert_delete(client, r, audit_enabled=audit_enabled),
        )

    return {KIND_CREATE: create_pair(), KIND_DELETE: delete_pair()}
