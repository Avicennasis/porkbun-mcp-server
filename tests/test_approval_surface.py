"""Tests for the approval surface and poller (#50877).

Offline throughout: the surface is two JSONL files and the handlers are local
callables, so nothing here needs a Matrix room or a provider.
"""

from __future__ import annotations

import json
from pathlib import Path

from porkbun_mcp.approval import ActionJournal, ActionState, project
from porkbun_mcp.approval_surface import (
    ApprovalPoller,
    Decision,
    FileApprovalSurface,
    poll_forever,
    summarize,
)


def _add_record(records: list[str], record) -> list[str]:
    return [*records, record.payload["name"]]


class TestSurface:
    def test_request_and_poll_round_trip(self, tmp_path: Path) -> None:
        surface = FileApprovalSurface(tmp_path / "req.jsonl", tmp_path / "dec.jsonl")
        journal = ActionJournal()
        record = journal.submit("dns.create", {"name": "a.example.com"})

        surface.request(record, summary="please approve")
        rows = [json.loads(line) for line in (tmp_path / "req.jsonl").read_text().splitlines()]
        assert rows == [{"action_id": record.id, "kind": "dns.create", "summary": "please approve"}]

        (tmp_path / "dec.jsonl").write_text(
            json.dumps({"action_id": record.id, "approved": True, "by": "leon"}) + "\n"
        )
        decisions = surface.poll()
        assert decisions == [Decision(action_id=record.id, approved=True, by="leon", note="")]

    def test_decisions_are_drained_not_reapplied(self, tmp_path: Path) -> None:
        """One approval must not become two provider calls on the next poll."""
        surface = FileApprovalSurface(tmp_path / "req.jsonl", tmp_path / "dec.jsonl")
        (tmp_path / "dec.jsonl").write_text(
            json.dumps({"action_id": 1, "approved": True, "by": "leon"}) + "\n"
        )

        assert len(surface.poll()) == 1
        assert surface.poll() == []

    def test_poll_with_no_decisions_is_empty(self, tmp_path: Path) -> None:
        surface = FileApprovalSurface(tmp_path / "req.jsonl", tmp_path / "dec.jsonl")
        assert surface.poll() == []


class TestPoller:
    def _poller(self, tmp_path: Path, journal: ActionJournal, applied: list[str]):
        surface = FileApprovalSurface(tmp_path / "req.jsonl", tmp_path / "dec.jsonl")

        def apply_fn(record) -> None:
            applied.append(record.payload["name"])

        return ApprovalPoller(journal, surface, {"dns.create": (apply_fn, None)}), surface

    def test_requests_each_pending_action_once(self, tmp_path: Path) -> None:
        journal = ActionJournal()
        journal.submit("dns.create", {"name": "a.example.com"})
        journal.submit("dns.create", {"name": "b.example.com"})
        poller, _ = self._poller(tmp_path, journal, [])

        assert poller.request_pending() == [1, 2]
        # A poller that ran twice, or restarted, must not spam the room.
        assert poller.request_pending() == []

    def test_an_approved_decision_applies(self, tmp_path: Path) -> None:
        journal = ActionJournal()
        record = journal.submit("dns.create", {"name": "a.example.com"})
        applied: list[str] = []
        poller, surface = self._poller(tmp_path, journal, applied)

        surface.request(record, summary="x")
        (tmp_path / "dec.jsonl").write_text(
            json.dumps({"action_id": record.id, "approved": True, "by": "leon"}) + "\n"
        )
        results = poller.drain()

        assert [r.outcome for r in results] == ["applied"]
        assert applied == ["a.example.com"]
        assert journal.get(record.id).state is ActionState.APPLIED

    def test_a_denied_decision_denies_without_calling_the_handler(self, tmp_path: Path) -> None:
        journal = ActionJournal()
        record = journal.submit("dns.create", {"name": "a.example.com"})
        applied: list[str] = []
        poller, surface = self._poller(tmp_path, journal, applied)

        surface.request(record, summary="x")
        (tmp_path / "dec.jsonl").write_text(
            json.dumps({"action_id": record.id, "approved": False, "by": "leon"}) + "\n"
        )
        results = poller.drain()

        assert [r.outcome for r in results] == ["denied"]
        assert applied == []
        assert project([], journal.pending(), _add_record).value == []

    def test_a_second_decision_for_the_same_action_is_not_reapplied(self, tmp_path: Path) -> None:
        journal = ActionJournal()
        record = journal.submit("dns.create", {"name": "a.example.com"})
        applied: list[str] = []
        poller, surface = self._poller(tmp_path, journal, applied)

        surface.request(record, summary="x")
        (tmp_path / "dec.jsonl").write_text(
            json.dumps({"action_id": record.id, "approved": True, "by": "leon"})
            + "\n"
            + json.dumps({"action_id": record.id, "approved": True, "by": "leon"})
            + "\n"
        )
        results = poller.drain()

        assert [r.outcome for r in results] == ["applied", "already-resolved"]
        assert applied == ["a.example.com"]

    def test_a_decision_for_an_unknown_action_is_reported(self, tmp_path: Path) -> None:
        journal = ActionJournal()
        poller, surface = self._poller(tmp_path, journal, [])

        (tmp_path / "dec.jsonl").write_text(
            json.dumps({"action_id": 99, "approved": True, "by": "leon"}) + "\n"
        )
        assert [r.outcome for r in poller.drain()] == ["unknown-action"]

    def test_an_approved_action_with_no_handler_is_not_applied(self, tmp_path: Path) -> None:
        """A wiring bug must not look like a successful approval."""
        journal = ActionJournal()
        record = journal.submit("dns.teleport", {"name": "a.example.com"})
        poller, surface = self._poller(tmp_path, journal, [])

        surface.request(record, summary="x")
        (tmp_path / "dec.jsonl").write_text(
            json.dumps({"action_id": record.id, "approved": True, "by": "leon"}) + "\n"
        )
        results = poller.drain()

        assert [r.outcome for r in results] == ["no-handler"]
        # Left PENDING, not APPLIED and not CLAIMED. Nothing was performed, so
        # the action stays undecided -- an operator can wire the handler and the
        # same approval can be replayed. Reporting it as applied would be the
        # lie this whole design exists to avoid.
        assert journal.get(record.id).state is ActionState.PENDING

    def test_run_once_announces_then_resolves(self, tmp_path: Path) -> None:
        journal = ActionJournal()
        record = journal.submit("dns.create", {"name": "a.example.com"})
        applied: list[str] = []
        poller, _ = self._poller(tmp_path, journal, applied)
        (tmp_path / "dec.jsonl").write_text(
            json.dumps({"action_id": record.id, "approved": True, "by": "leon"}) + "\n"
        )

        results = poller.run_once()

        assert [r.outcome for r in results] == ["applied"]
        rows = (tmp_path / "req.jsonl").read_text().splitlines()
        assert len(rows) == 1, "run_once must announce exactly once"

    def test_poll_forever_stops_on_the_condition(self, tmp_path: Path) -> None:
        """No real sleeping: the stopping condition is injected."""
        journal = ActionJournal()
        poller, _ = self._poller(tmp_path, journal, [])
        rounds: list[int] = []
        calls = {"n": 0}

        def should_stop() -> bool:
            calls["n"] += 1
            return calls["n"] > 2

        poll_forever(
            poller,
            interval_s=0,
            should_stop=should_stop,
            on_round=lambda r: rounds.append(len(list(r))),
        )
        assert rounds == [0, 0]


class TestSummarize:
    def test_includes_the_payload_so_the_approver_sees_what_they_approve(self) -> None:
        journal = ActionJournal()
        record = journal.submit("dns.create", {"name": "a.example.com", "type": "TXT"})
        summary = summarize(record)
        assert "dns.create" in summary
        assert "name=a.example.com" in summary
        assert "type=TXT" in summary
