"""Tests for the Matrix approval surface (#50877).

Offline: the Matrix client is faked, so no room, no homeserver and no vault.
The behaviours under test are the ones that decide whether a human's answer is
honoured exactly once.
"""

from __future__ import annotations

import json
from pathlib import Path

from porkbun_mcp.approval import ActionJournal
from porkbun_mcp.approval_surface import ApprovalPoller
from porkbun_mcp.matrix_surface import APPROVE, DENY, MatrixApprovalSurface


class FakeMatrix:
    """Records sends; replays reactions keyed by event id."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self.reactions_by_event: dict[str, list[str]] = {}
        self.fail_reactions_for: set[str] = set()
        self._n = 0

    def send(self, room: str, body: str) -> str:
        self._n += 1
        event_id = f"$ev{self._n}"
        self.sent.append((room, body))
        return event_id

    def reactions(self, room: str, event_id: str) -> list[str]:
        if event_id in self.fail_reactions_for:
            raise RuntimeError("homeserver unreachable")
        return self.reactions_by_event.get(event_id, [])


def _surface(tmp_path: Path) -> tuple[FakeMatrix, MatrixApprovalSurface]:
    client = FakeMatrix()
    return client, MatrixApprovalSurface(client, "!room:example", tmp_path / "events.json")


class TestRequest:
    def test_request_posts_the_action_and_the_summary(self, tmp_path: Path) -> None:
        client, surface = _surface(tmp_path)
        journal = ActionJournal()
        record = journal.submit("dns.create", {"name": "a.example.com"})

        surface.request(record, summary="dns.create(name=a.example.com)")

        assert len(client.sent) == 1
        _, body = client.sent[0]
        assert "dns.create(name=a.example.com)" in body
        assert str(record.id) in body
        assert APPROVE in body and DENY in body

    def test_the_event_map_survives_a_restart(self, tmp_path: Path) -> None:
        """A poller that restarted between asking and answering must still work."""
        client, surface = _surface(tmp_path)
        journal = ActionJournal()
        record = journal.submit("dns.create", {"name": "a.example.com"})
        surface.request(record, summary="x")

        # A brand-new surface over the same state file: what a restart looks like.
        rebuilt = MatrixApprovalSurface(client, "!room:example", tmp_path / "events.json")
        client.reactions_by_event["$ev1"] = [APPROVE]

        decisions = rebuilt.poll()
        assert [d.action_id for d in decisions] == [record.id]
        assert decisions[0].approved is True


class TestPoll:
    def test_no_reaction_means_still_pending(self, tmp_path: Path) -> None:
        client, surface = _surface(tmp_path)
        journal = ActionJournal()
        surface.request(journal.submit("dns.create", {"name": "a"}), summary="x")

        assert surface.poll() == []
        # And it is still tracked, so the answer can arrive later.
        assert json.loads((tmp_path / "events.json").read_text()) != {}

    def test_an_unknown_reaction_is_ignored_not_guessed(self, tmp_path: Path) -> None:
        client, surface = _surface(tmp_path)
        journal = ActionJournal()
        surface.request(journal.submit("dns.create", {"name": "a"}), summary="x")

        client.reactions_by_event["$ev1"] = ["👀", "✅ "]  # neither is in the set
        assert surface.poll() == []

    def test_an_answer_is_read_once(self, tmp_path: Path) -> None:
        client, surface = _surface(tmp_path)
        journal = ActionJournal()
        surface.request(journal.submit("dns.create", {"name": "a"}), summary="x")
        client.reactions_by_event["$ev1"] = [APPROVE]

        assert len(surface.poll()) == 1
        # One decision must not become two provider calls on the next poll.
        assert surface.poll() == []

    def test_a_read_failure_keeps_the_request(self, tmp_path: Path) -> None:
        """A network blip must not silently drop a pending request."""
        client, surface = _surface(tmp_path)
        journal = ActionJournal()
        surface.request(journal.submit("dns.create", {"name": "a"}), summary="x")
        client.fail_reactions_for.add("$ev1")

        assert surface.poll() == []
        assert json.loads((tmp_path / "events.json").read_text()) != {}

        # Recovery: the answer is still readable afterwards.
        client.fail_reactions_for.clear()
        client.reactions_by_event["$ev1"] = [DENY]
        decisions = surface.poll()
        assert len(decisions) == 1 and decisions[0].approved is False

    def test_a_deny_maps_to_a_denial(self, tmp_path: Path) -> None:
        client, surface = _surface(tmp_path)
        journal = ActionJournal()
        surface.request(journal.submit("dns.create", {"name": "a"}), summary="x")
        client.reactions_by_event["$ev1"] = [DENY]

        assert surface.poll()[0].approved is False


class TestEndToEnd:
    def test_a_deny_in_the_room_denies_in_the_journal(self, tmp_path: Path) -> None:
        """The whole path: request out, reaction in, journal resolved."""
        client, surface = _surface(tmp_path)
        journal = ActionJournal()
        journal.submit("dns.create", {"name": "a.example.com"})
        applied: list[str] = []

        poller = ApprovalPoller(
            journal, surface, {"dns.create": (lambda r: applied.append(r.kind), None)}
        )
        poller.request_pending()
        assert len(client.sent) == 1

        client.reactions_by_event["$ev1"] = [DENY]
        results = poller.drain()

        assert [r.outcome for r in results] == ["denied"]
        assert applied == []

    def test_an_approve_in_the_room_applies_once(self, tmp_path: Path) -> None:
        client, surface = _surface(tmp_path)
        journal = ActionJournal()
        journal.submit("dns.create", {"name": "a.example.com"})
        applied: list[str] = []

        poller = ApprovalPoller(
            journal, surface, {"dns.create": (lambda r: applied.append(r.kind), None)}
        )
        poller.request_pending()
        client.reactions_by_event["$ev1"] = [APPROVE]

        assert [r.outcome for r in poller.drain()] == ["applied"]
        assert applied == ["dns.create"]
        # A second round finds nothing: the request map was drained.
        assert poller.drain() == []
        assert applied == ["dns.create"]
