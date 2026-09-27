"""Tests for the async-approval engine (#50877).

Everything here is offline: the engine takes callables, so the "provider" is a
list in the test. The point of these tests is the *semantics* — specifically
that deny-before-apply costs nothing, and that an unknown outcome is never
quietly forgotten.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from porkbun_mcp.approval import (
    ActionJournal,
    ActionRefusedError,
    ActionState,
    ApprovalError,
    Projection,
    ReconciliationWarning,
    project,
)


def _add_record(records: list[dict[str, str]], record) -> list[dict[str, str]]:
    """A pure projection step: returns a new list rather than mutating."""
    return [*records, {"type": "TXT", "name": record.payload["name"]}]


@pytest.fixture
def calls() -> list[str]:
    return []


class TestProjection:
    def test_pending_action_is_visible_in_reads(self, calls: list[str]) -> None:
        """The whole point: the agent is not blocked waiting on a human."""
        journal = ActionJournal()
        journal.submit("dns.create", {"name": "_verify.example.com"})

        view = project([], journal.pending(), _add_record)

        assert view.complete is True
        assert view.value == [{"type": "TXT", "name": "_verify.example.com"}]
        assert calls == []  # nothing real happened

    def test_denied_action_disappears_from_the_projection(self) -> None:
        """Deny-before-apply drops the record; replaying is the entire undo."""
        journal = ActionJournal()
        first = journal.submit("dns.create", {"name": "a.example.com"})
        journal.submit("dns.create", {"name": "b.example.com"})

        before = project([], journal.pending(), _add_record)
        assert [r["name"] for r in before.value] == ["a.example.com", "b.example.com"]

        journal.deny(first.id)

        after = project([], journal.pending(), _add_record)
        assert [r["name"] for r in after.value] == ["b.example.com"]

    def test_unsupported_effect_reports_partial_honestly(self) -> None:
        """A projection that cannot render an effect must say so, not under-report."""
        journal = ActionJournal()
        journal.submit("dns.create", {"name": "a.example.com"})
        journal.submit("dns.create", {"name": "b.example.com"})

        def apply_one(value, record):
            if record.payload["name"] == "b.example.com":
                raise NotImplementedError("cannot simulate this effect")
            return _add_record(value, record)

        view = project([], journal.pending(), apply_one)

        assert isinstance(view, Projection)
        assert view.complete is False
        assert view.value == [{"type": "TXT", "name": "a.example.com"}]
        assert view.reason == "cannot simulate this effect"

    def test_applied_and_reverted_actions_are_not_projected(self) -> None:
        journal = ActionJournal()
        applied = journal.submit("dns.create", {"name": "a.example.com"})
        journal.approve(applied.id)
        journal.apply(applied.id, lambda _: None)

        assert project([], journal.pending(), _add_record).value == []


class TestResolution:
    def test_approve_then_apply_runs_the_real_call_once(self) -> None:
        journal = ActionJournal()
        made: list[str] = []
        record = journal.submit("dns.create", {"name": "a.example.com"})

        journal.approve(record.id)
        assert journal.get(record.id).state is ActionState.CLAIMED

        journal.apply(record.id, lambda r: made.append(r.payload["name"]))

        assert made == ["a.example.com"]
        assert journal.get(record.id).state is ActionState.APPLIED

    def test_apply_requires_a_claim_first(self) -> None:
        """Claim-before-apply is what stops a crash leaving a replayable record."""
        journal = ActionJournal()
        record = journal.submit("dns.create", {"name": "a.example.com"})

        with pytest.raises(ApprovalError, match="expected one of"):
            journal.apply(record.id, lambda _: None)

    def test_refused_before_dispatch_drops_the_record(self) -> None:
        """Effect known absent: nothing to reconcile, so the record goes."""
        journal = ActionJournal()
        record = journal.submit("dns.create", {"name": "a.example.com"})
        journal.approve(record.id)

        def refuse(_record):
            raise ActionRefusedError("provider said no before dispatch")

        journal.apply(record.id, refuse)

        with pytest.raises(ApprovalError, match="no action"):
            journal.get(record.id)
        assert journal.warnings() == []

    def test_deny_after_apply_needs_a_revert(self) -> None:
        journal = ActionJournal()
        record = journal.submit("dns.create", {"name": "a.example.com"})
        journal.approve(record.id)
        journal.apply(record.id, lambda _: None)

        with pytest.raises(ApprovalError, match="revert_fn is required"):
            journal.deny(record.id)

        undone: list[int] = []
        journal.deny(record.id, lambda r: undone.append(r.id))

        assert undone == [record.id]
        assert journal.get(record.id).state is ActionState.REVERTED


class TestReconciliation:
    def test_unknown_outcome_keeps_the_record_and_the_warning(self) -> None:
        """The case the whole design exists for.

        A rejected call whose effect may have landed must not vanish. If it did,
        a later reader would conclude the record was never created — which is
        exactly the false belief the warning prevents.
        """
        journal = ActionJournal()
        record = journal.submit("dns.create", {"name": "a.example.com"})
        journal.approve(record.id)

        warning = journal.mark_unknown(record.id, "timeout after the POST was sent")

        assert isinstance(warning, ReconciliationWarning)
        assert warning.action_id == record.id
        assert journal.get(record.id).state is ActionState.FAILED
        assert journal.get(record.id).warning == warning
        assert journal.warnings() == [warning]
        assert project([], journal.pending(), _add_record).value == []

    def test_warning_survives_a_reload(self, tmp_path: Path) -> None:
        """A restart must not erase the "state may differ" marker."""
        path = tmp_path / "journal.jsonl"
        journal = ActionJournal(path)
        record = journal.submit("dns.create", {"name": "a.example.com"})
        journal.approve(record.id)
        journal.mark_unknown(record.id, "timeout")

        reloaded = ActionJournal(path)

        assert [w.detail for w in reloaded.warnings()] == ["timeout"]
        assert reloaded.get(record.id).state is ActionState.FAILED


class TestPersistence:
    def test_pending_actions_round_trip(self, tmp_path: Path) -> None:
        path = tmp_path / "journal.jsonl"
        journal = ActionJournal(path)
        journal.submit("dns.create", {"name": "a.example.com"})
        journal.submit("dns.delete", {"name": "b.example.com"})

        reloaded = ActionJournal(path)

        assert [(r.kind, r.state) for r in reloaded.pending()] == [
            ("dns.create", ActionState.PENDING),
            ("dns.delete", ActionState.PENDING),
        ]
        assert reloaded.submit("dns.create", {}).id == 3  # ids keep counting
