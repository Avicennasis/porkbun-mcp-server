"""Tests for the DNS approval handlers (#50877).

Offline: the two `*_impl` functions are patched, so nothing reaches Porkbun.

The rule under test is the one that decides whether `deny` tells the truth:
**a revert must be able to run from the record alone**, because the poller may
resolve an approval hours later from a process that restarted in between.
"""

from __future__ import annotations

from unittest import mock

import pytest

from porkbun_mcp import approval_handlers
from porkbun_mcp.approval import ActionJournal, ActionState
from porkbun_mcp.approval_handlers import (
    KIND_CREATE,
    KIND_DELETE,
    UnrevertibleError,
    build_handlers,
)

CREATE_PAYLOAD = {
    "domain": "example.com",
    "type": "TXT",
    "name": "_verify",
    "content": "tok",
    "reason": "test",
}


class TestCreate:
    def test_apply_creates_and_captures_the_id_for_the_revert(self) -> None:
        client = object()
        handlers = build_handlers(client, audit_enabled=False)  # type: ignore[arg-type]
        journal = ActionJournal()
        record = journal.submit(KIND_CREATE, dict(CREATE_PAYLOAD))

        with mock.patch.object(
            approval_handlers.dns, "create_dns_record_impl", return_value={"id": 42}
        ) as made:
            handlers[KIND_CREATE][0](record)

        assert made.call_args.args[0] is client
        assert made.call_args.args[1] == "example.com"
        assert made.call_args.kwargs["type"] == "TXT"
        # The revert's entire input. Without this the delete would have no target.
        assert record.payload["created_record_id"] == 42

    def test_the_captured_id_survives_a_restart(self, tmp_path) -> None:
        """The poller may restart between applying and reverting."""
        journal = ActionJournal(tmp_path / "j.jsonl")
        record = journal.submit(KIND_CREATE, dict(CREATE_PAYLOAD))
        journal.approve(record.id)

        handlers = build_handlers(object(), audit_enabled=False)  # type: ignore[arg-type]
        with mock.patch.object(
            approval_handlers.dns, "create_dns_record_impl", return_value={"id": 7}
        ):
            journal.apply(record.id, handlers[KIND_CREATE][0])

        reloaded = ActionJournal(tmp_path / "j.jsonl")
        assert reloaded.get(record.id).payload["created_record_id"] == 7

    def test_revert_deletes_the_created_record(self) -> None:
        handlers = build_handlers(object(), audit_enabled=False)  # type: ignore[arg-type]
        journal = ActionJournal()
        record = journal.submit(KIND_CREATE, dict(CREATE_PAYLOAD))
        with mock.patch.object(
            approval_handlers.dns, "create_dns_record_impl", return_value={"id": 99}
        ):
            handlers[KIND_CREATE][0](record)

        with mock.patch.object(approval_handlers.dns, "delete_dns_record_impl") as removed:
            handlers[KIND_CREATE][1](record)

        assert removed.call_args.args[1] == "example.com"
        assert removed.call_args.args[2] == "99"

    def test_reverting_an_action_that_never_applied_is_a_no_op(self) -> None:
        """Nothing was created, so there is nothing to delete — not an error."""
        handlers = build_handlers(object(), audit_enabled=False)  # type: ignore[arg-type]
        journal = ActionJournal()
        record = journal.submit(KIND_CREATE, dict(CREATE_PAYLOAD))

        with mock.patch.object(approval_handlers.dns, "delete_dns_record_impl") as removed:
            handlers[KIND_CREATE][1](record)

        removed.assert_not_called()


class TestDelete:
    def _payload(self) -> dict:
        return {
            "domain": "example.com",
            "record_id": "12",
            "reason": "test",
            # The inverse of a delete is a re-create, so the contents have to be
            # carried. This is what makes the delete revertible at all.
            "record": {"type": "TXT", "name": "_verify", "content": "tok", "ttl": 600},
        }

    def test_apply_deletes(self) -> None:
        handlers = build_handlers(object(), audit_enabled=False)  # type: ignore[arg-type]
        journal = ActionJournal()
        record = journal.submit(KIND_DELETE, self._payload())

        with mock.patch.object(approval_handlers.dns, "delete_dns_record_impl") as removed:
            handlers[KIND_DELETE][0](record)

        assert removed.call_args.args[2] == "12"

    def test_apply_refuses_when_the_record_was_not_captured(self) -> None:
        """Refuse BEFORE the call.

        Deleting and only then discovering we cannot put it back is the one
        ordering that loses data.
        """
        handlers = build_handlers(object(), audit_enabled=False)  # type: ignore[arg-type]
        journal = ActionJournal()
        payload = self._payload()
        del payload["record"]
        record = journal.submit(KIND_DELETE, payload)

        with (
            mock.patch.object(approval_handlers.dns, "delete_dns_record_impl") as removed,
            pytest.raises(UnrevertibleError),
        ):
            handlers[KIND_DELETE][0](record)

        removed.assert_not_called()

    def test_revert_recreates_from_the_captured_record(self) -> None:
        handlers = build_handlers(object(), audit_enabled=False)  # type: ignore[arg-type]
        journal = ActionJournal()
        record = journal.submit(KIND_DELETE, self._payload())

        with mock.patch.object(
            approval_handlers.dns, "create_dns_record_impl", return_value={"id": 1}
        ) as made:
            handlers[KIND_DELETE][1](record)

        assert made.call_args.args[1] == "example.com"
        assert made.call_args.kwargs["type"] == "TXT"
        assert made.call_args.kwargs["content"] == "tok"


class TestRegistry:
    def test_only_the_wired_kinds_are_present(self) -> None:
        handlers = build_handlers(object(), audit_enabled=False)  # type: ignore[arg-type]
        assert set(handlers) == {KIND_CREATE, KIND_DELETE}
        for apply_fn, revert_fn in handlers.values():
            assert callable(apply_fn) and callable(revert_fn)

    def test_an_unwired_kind_is_not_silently_handled(self) -> None:
        handlers = build_handlers(object(), audit_enabled=False)  # type: ignore[arg-type]
        assert "dns.teleport" not in handlers


class TestThroughThePoller:
    def test_approve_then_deny_applies_then_reverts(self) -> None:
        """The full lifecycle, through the journal rather than the bare callables."""
        journal = ActionJournal()
        record = journal.submit(KIND_CREATE, dict(CREATE_PAYLOAD))
        handlers = build_handlers(object(), audit_enabled=False)  # type: ignore[arg-type]

        with mock.patch.object(
            approval_handlers.dns, "create_dns_record_impl", return_value={"id": 5}
        ):
            journal.approve(record.id)
            journal.apply(record.id, handlers[KIND_CREATE][0])
        assert journal.get(record.id).state is ActionState.APPLIED

        with mock.patch.object(approval_handlers.dns, "delete_dns_record_impl") as removed:
            journal.deny(record.id, handlers[KIND_CREATE][1])

        assert removed.call_args.args[2] == "5"
        assert journal.get(record.id).state is ActionState.REVERTED
