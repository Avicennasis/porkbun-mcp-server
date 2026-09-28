"""The human side of async approval: a surface, and a poller that drains it.

`approval.py` has the engine — submit, project, apply, deny, mark_unknown. This
module is the other half: how a decision actually arrives (#50877).

The problem it solves is specific. The fleet's existing approval is
`matrix_request_approval` + `matrix_await_approval`, and the *await* is the whole
issue: it blocks the session until a human answers, so an unattended run either
stalls on the first gated call or has to be pre-authorised wholesale.

The fix is not a better prompt. It is to stop the agent doing the waiting:

    agent submits  ->  journal PENDING, effect projected, agent carries on
    poller posts   ->  a human sees the request
    human decides  ->  poller applies or denies, out of band

So the surface has exactly two operations — `request()` and `poll()` — and
**neither blocks**. Whoever calls them is the poller, which is a separate process
from the agent.

The Matrix call is deliberately behind a Protocol. The room is the only part
that needs a live network, so keeping it injectable means the resolution logic is
testable offline, and swapping the transport does not touch it.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from porkbun_mcp.approval import ActionJournal, ActionRecord

#: kind -> (apply, revert). A kind with no entry cannot be applied, which is a
#: deliberate failure rather than a silent approve: an unknown kind means
#: somebody changed one side and not the other.
Handler = tuple[Callable[[ActionRecord], None], Callable[[ActionRecord], None] | None]


@dataclass(frozen=True)
class Decision:
    """One human answer, as it arrives from a surface."""

    action_id: int
    approved: bool
    by: str
    note: str = ""


class ApprovalSurface(Protocol):
    """Non-blocking request/decision transport. Implemented per channel."""

    def request(self, record: ActionRecord, *, summary: str) -> None:
        """Publish a request. Must not wait for an answer."""
        ...

    def poll(self) -> list[Decision]:
        """Return decisions made since the last poll. Must not wait."""
        ...


class FileApprovalSurface:
    """A surface backed by two JSONL files — requests out, decisions in.

    Enough to run and test the loop end to end, and the shape a Matrix surface
    would keep: the poller writes a request line, a human (or a bridge that
    watches the room) appends a decision line, and `poll()` drains them.

    Append-only on purpose. A decision cannot be withdrawn by rewriting history,
    which matters because the journal's answer to a withdrawn decision would
    otherwise be "nothing happened".
    """

    def __init__(self, requests: Path, decisions: Path) -> None:
        self._requests = requests
        self._decisions = decisions

    def request(self, record: ActionRecord, *, summary: str) -> None:
        self._requests.parent.mkdir(parents=True, exist_ok=True)
        with self._requests.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps({"action_id": record.id, "kind": record.kind, "summary": summary}) + "\n"
            )

    def poll(self) -> list[Decision]:
        if not self._decisions.exists():
            return []
        out: list[Decision] = []
        for line in self._decisions.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            out.append(
                Decision(
                    action_id=int(row["action_id"]),
                    approved=bool(row["approved"]),
                    by=str(row.get("by", "unknown")),
                    note=str(row.get("note", "")),
                )
            )
        # Drained, not re-read: a decision resolves an action once. Re-applying
        # on a later poll would be a second provider call for one approval.
        self._decisions.write_text("", encoding="utf-8")
        return out


@dataclass(frozen=True)
class Resolution:
    """What the poller did with one decision."""

    decision: Decision
    outcome: str
    detail: str = ""


def summarize(record: ActionRecord) -> str:
    """One line a human can decide from.

    Deliberately includes the payload: an approver shown only an action id is
    being asked to rubber-stamp. The gatekeeper work this follows puts the same
    weight on approval text being readable.
    """
    payload = ", ".join(f"{k}={v}" for k, v in sorted(record.payload.items()))
    return f"#{record.id} {record.kind}({payload})"


class ApprovalPoller:
    """Drains a surface and resolves the journal. Never called by the agent."""

    def __init__(
        self,
        journal: ActionJournal,
        surface: ApprovalSurface,
        handlers: dict[str, Handler],
    ) -> None:
        self._journal = journal
        self._surface = surface
        self._handlers = handlers
        self._requested: set[int] = set()

    def request_pending(self) -> list[int]:
        """Publish a request for every undecided action not yet announced.

        Idempotent per action: a poller that restarted, or ran twice, must not
        spam the room with the same request.
        """
        fresh = [r for r in self._journal.pending() if r.id not in self._requested]
        for record in fresh:
            self._surface.request(record, summary=summarize(record))
            self._requested.add(record.id)
        return [r.id for r in fresh]

    def drain(self) -> list[Resolution]:
        """Apply every decision the surface has."""
        return [self._resolve(d) for d in self._surface.poll()]

    def run_once(self) -> list[Resolution]:
        """One pass: announce, then resolve. Returns what was resolved."""
        self.request_pending()
        return self.drain()

    def _resolve(self, decision: Decision) -> Resolution:
        try:
            record = self._journal.get(decision.action_id)
        except Exception:  # ApprovalError, and anything a subclass raises
            return Resolution(decision, "unknown-action", "no such action in the journal")

        if record.state.value not in ("staged", "pending", "claimed"):
            # Already resolved by an earlier decision or a reconcile. Saying so
            # is better than a silent no-op an operator cannot tell from a bug.
            return Resolution(decision, "already-resolved", f"state={record.state}")

        if not decision.approved:
            self._journal.deny(decision.action_id)
            return Resolution(decision, "denied", f"by {decision.by}")

        handler = self._handlers.get(record.kind)
        if handler is None:
            # Refuse rather than pass: an unhandled kind is a wiring bug, and
            # approving it would apply nothing while looking like success.
            return Resolution(decision, "no-handler", f"kind={record.kind}")

        apply_fn, _revert = handler
        self._journal.approve(decision.action_id)
        self._journal.apply(decision.action_id, apply_fn)
        return Resolution(decision, "applied", f"by {decision.by}")


def poll_forever(
    poller: ApprovalPoller,
    *,
    interval_s: float = 5.0,
    should_stop: Callable[[], bool] | None = None,
    on_round: Callable[[Iterable[Resolution]], None] | None = None,
) -> None:
    """The poller's loop. Lives in its own process, not in the agent's.

    Kept here rather than in a `__main__` so the stopping condition and the
    interval are testable without sleeping for real.
    """
    import time

    stop = should_stop or (lambda: False)
    while not stop():
        resolutions = poller.run_once()
        if on_round is not None:
            on_round(resolutions)
        time.sleep(interval_s)
