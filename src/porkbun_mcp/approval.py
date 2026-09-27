"""Async human approval for mutating tool calls, by simulation.

This is the pattern from Cloudflare OS's Gatekeepers, reimplemented without any
Cloudflare dependency (see the #50877 analysis). A mutating call is **submitted**
rather than executed: it becomes a ``PENDING`` record, and its effect is
**projected** onto subsequent reads so the agent is never blocked waiting on a
human. A human then approves it — and it applies for real — or denies it.

The part that makes this usable is that the projection is a **pure replay of the
journal**, not a stored fiction. Denying an action that never reached the provider
therefore costs nothing: drop the record and replay again. There is no undo,
because there was never anything to undo.

Two failure modes are kept distinct on purpose, because collapsing them is how
this pattern turns into a lie:

- ``ActionRefusedError`` — the provider call refused *before* it was dispatched.
  The effect is known absent, so the record can be dropped cleanly.
- :func:`mark_unknown` — the provider may have committed. The record is **kept**
  and carries a :class:`ReconciliationWarning`, so nobody later reads a clean
  journal and concludes the effect never happened.

Nothing here talks to Porkbun. The engine takes callables, so it is testable
offline and can be lifted to another MCP server unchanged.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Generic, TypeVar

T = TypeVar("T")


class ActionState(StrEnum):
    """Lifecycle of a submitted action.

    ``PENDING`` is undecided. ``CLAIMED`` is approved and in flight. ``APPLIED``
    and ``REVERTED`` are terminal. ``FAILED`` is terminal but may be *unknown* —
    check :attr:`ActionRecord.warning`.
    """

    STAGED = "staged"
    PENDING = "pending"
    CLAIMED = "claimed"
    APPLIED = "applied"
    FAILED = "failed"
    REVERTED = "reverted"


#: States whose effect must be visible in reads. Matches Cloudflare's PROJECTED.
PROJECTED: tuple[ActionState, ...] = (ActionState.PENDING, ActionState.CLAIMED)

#: States with no human decision yet.
UNDECIDED: tuple[ActionState, ...] = (ActionState.PENDING,)

TERMINAL: tuple[ActionState, ...] = (
    ActionState.APPLIED,
    ActionState.FAILED,
    ActionState.REVERTED,
)


class ApprovalError(RuntimeError):
    """A transition was refused."""


class ActionRefusedError(RuntimeError):
    """The provider refused *before* dispatch, so the effect is known absent.

    Safe to drop the record: nothing was committed, so there is nothing to
    reconcile. Contrast :func:`mark_unknown`.
    """


@dataclass(frozen=True)
class ReconciliationWarning:
    """A durable "the real state may differ" marker.

    Survives the resolution of its action, because the point is that a later
    reader must not conclude the effect never happened.
    """

    action_id: int
    kind: str
    detail: str


@dataclass
class ActionRecord:
    """One submitted action."""

    id: int
    kind: str
    payload: dict[str, Any]
    state: ActionState = ActionState.STAGED
    created_at: float = field(default_factory=time.time)
    warning: ReconciliationWarning | None = None

    @property
    def projected(self) -> bool:
        """Whether this action's effect belongs in a read right now."""
        return self.state in PROJECTED


@dataclass(frozen=True)
class Projection(Generic[T]):
    """The result of replaying pending actions onto a base value.

    ``complete`` is ``False`` when replay stopped at an effect it could not
    project. That is reported rather than swallowed: a projection that quietly
    under-reports is worse than one that admits its limit.
    """

    value: T
    complete: bool
    applied: tuple[int, ...]
    stopped_at: int | None = None
    reason: str | None = None


def project(
    base: T,
    records: Iterable[ActionRecord],
    apply_fn: Callable[[T, ActionRecord], T],
) -> Projection[T]:
    """Replay ``records`` onto ``base``, stopping at the first unsupported effect.

    ``apply_fn`` must return the next value rather than mutate in place, so a
    partial result stays honest.
    """
    value = base
    applied: list[int] = []
    for record in sorted(records, key=lambda r: r.id):
        if not record.projected:
            continue
        try:
            value = apply_fn(value, record)
        except NotImplementedError as exc:
            return Projection(value, False, tuple(applied), record.id, str(exc))
        applied.append(record.id)
    return Projection(value, True, tuple(applied))


class ActionJournal:
    """Durable action store.

    Append-only JSONL, matching ``audit.py``'s storage style. In-memory state is
    authoritative during a run; the file exists so a restart does not lose
    undecided actions.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._records: dict[int, ActionRecord] = {}
        self._next_id = 1
        self._warnings: list[ReconciliationWarning] = []
        if path is not None and path.exists():
            self._load()

    # ---- persistence -----------------------------------------------------

    def _load(self) -> None:
        assert self._path is not None
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("_warning"):
                self._warnings.append(
                    ReconciliationWarning(row["action_id"], row["kind"], row["detail"])
                )
                continue
            record = ActionRecord(
                id=row["id"],
                kind=row["kind"],
                payload=row["payload"],
                state=ActionState(row["state"]),
                created_at=row["created_at"],
            )
            self._records[record.id] = record
            self._next_id = max(self._next_id, record.id + 1)

    def _append(self, row: dict[str, Any]) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")

    def _persist(self, record: ActionRecord) -> None:
        self._append(
            {
                "id": record.id,
                "kind": record.kind,
                "payload": record.payload,
                "state": str(record.state),
                "created_at": record.created_at,
            }
        )

    # ---- transitions -----------------------------------------------------

    def submit(self, kind: str, payload: dict[str, Any]) -> ActionRecord:
        """Record an action as ``PENDING`` — its effect becomes projected."""
        record = ActionRecord(id=self._next_id, kind=kind, payload=payload)
        self._next_id += 1
        record.state = ActionState.PENDING
        self._records[record.id] = record
        self._persist(record)
        return record

    def get(self, action_id: int) -> ActionRecord:
        try:
            return self._records[action_id]
        except KeyError:
            raise ApprovalError(f"no action {action_id}") from None

    def pending(self) -> list[ActionRecord]:
        """Undecided actions, oldest first."""
        return [
            r for r in sorted(self._records.values(), key=lambda r: r.id) if r.state in UNDECIDED
        ]

    def warnings(self) -> list[ReconciliationWarning]:
        """Every reconciliation warning ever recorded."""
        return list(self._warnings)

    def _require(self, action_id: int, allowed: Sequence[ActionState]) -> ActionRecord:
        record = self.get(action_id)
        if record.state not in allowed:
            raise ApprovalError(
                f"action {action_id} is {record.state}; expected one of {[str(s) for s in allowed]}"
            )
        return record

    def approve(self, action_id: int) -> ActionRecord:
        """Move an action to ``CLAIMED``, ready to apply."""
        record = self._require(action_id, [ActionState.STAGED, ActionState.PENDING])
        record.state = ActionState.CLAIMED
        self._persist(record)
        return record

    def apply(self, action_id: int, apply_fn: Callable[[ActionRecord], None]) -> ActionRecord:
        """Run the real provider call for an approved action.

        The claim happens **before** the call, so a crash between the call and
        its bookkeeping cannot leave the record replayable.
        """
        record = self._require(action_id, [ActionState.CLAIMED])
        try:
            apply_fn(record)
        except ActionRefusedError:
            # Refused before dispatch: the effect is known absent, so the record
            # can be dropped outright rather than left dangling.
            del self._records[action_id]
            return record
        record.state = ActionState.APPLIED
        self._persist(record)
        return record

    def deny(
        self, action_id: int, revert_fn: Callable[[ActionRecord], None] | None = None
    ) -> ActionRecord:
        """Deny an action.

        Undecided actions are **dropped** — nothing was committed, so removing
        the record is the whole operation and the projection recomputes without
        it. An applied action needs ``revert_fn`` instead.
        """
        record = self.get(action_id)
        if record.state in UNDECIDED or record.state is ActionState.CLAIMED:
            del self._records[action_id]
            return record
        if record.state is ActionState.APPLIED:
            if revert_fn is None:
                raise ApprovalError(
                    f"action {action_id} is applied; a revert_fn is required to deny it"
                )
            revert_fn(record)
            record.state = ActionState.REVERTED
            self._persist(record)
            return record
        raise ApprovalError(f"action {action_id} is {record.state}; nothing to deny")

    def mark_unknown(self, action_id: int, detail: str) -> ReconciliationWarning:
        """Record that a provider call may have taken effect.

        The record is **kept**. A reviewer must not be able to read a clean
        journal and conclude the effect never happened.
        """
        record = self._require(action_id, [ActionState.CLAIMED, ActionState.PENDING])
        warning = ReconciliationWarning(record.id, record.kind, detail)
        record.state = ActionState.FAILED
        record.warning = warning
        self._warnings.append(warning)
        self._persist(record)
        self._append(
            {
                "_warning": True,
                "action_id": warning.action_id,
                "kind": warning.kind,
                "detail": warning.detail,
            }
        )
        return warning
