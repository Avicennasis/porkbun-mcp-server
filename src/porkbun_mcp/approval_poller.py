"""Run the approval poller. This is what the systemd unit starts.

Kept as its own module so the unit's `ExecStart` is a stable, importable target
rather than a path into the checkout.

    python3 -m porkbun_mcp.approval_poller

The agent never runs this. It is a **separate process**, and that separation is
the entire point: the agent submits and moves on, while this waits.

Environment:
    APPROVAL_JOURNAL   journal JSONL (default ~/.local/state/porkbun-mcp/approval-journal.jsonl)
    APPROVAL_STATE     action-id -> Matrix event-id map (see matrix_surface)
    APPROVAL_INTERVAL  seconds between rounds (default 5)
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from porkbun_mcp.approval import ActionJournal
from porkbun_mcp.approval_surface import ApprovalPoller, Handler, poll_forever
from porkbun_mcp.matrix_surface import build_surface

log = logging.getLogger("porkbun_mcp.approval_poller")


def handlers() -> dict[str, Handler]:
    """kind -> (apply, revert), for the kinds this server knows how to apply.

    Every entry wraps a real provider call, and the journal is general while the
    calls are not. An action of an unwired kind still comes back as
    `no-handler` and stays PENDING — visible and retryable — rather than being
    silently dropped or, worse, reported as applied.

    DNS is wired (#50877). A client is built here because this is the entry
    point; `build_handlers(client)` in `approval_handlers` is the testable form.
    """
    from porkbun_mcp.approval_handlers import build_handlers
    from porkbun_mcp.client import PorkbunClient
    from porkbun_mcp.config import Config

    cfg = Config.from_env()
    cfg.require_credentials()
    return build_handlers(PorkbunClient(cfg), audit_enabled=cfg.audit_enabled)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.environ.get("APPROVAL_LOG_LEVEL", "INFO"),
        format="%(asctime)s [approval-poller] %(message)s",
        stream=sys.stderr,
    )

    journal_path = Path(
        os.environ.get(
            "APPROVAL_JOURNAL",
            str(Path.home() / ".local/state/porkbun-mcp/approval-journal.jsonl"),
        )
    )
    journal = ActionJournal(journal_path)
    surface = build_surface()
    poller = ApprovalPoller(journal, surface, handlers())

    interval = float(os.environ.get("APPROVAL_INTERVAL", "5"))

    pending = len(journal.pending())
    log.info(
        "watching %d pending action(s); journal=%s interval=%ss", pending, journal_path, interval
    )

    def on_round(resolutions) -> None:
        for resolution in resolutions:
            log.info(
                "action %s -> %s (%s)",
                resolution.decision.action_id,
                resolution.outcome,
                resolution.detail or "no detail",
            )

    poll_forever(poller, interval_s=interval, on_round=on_round)
    return 0


if __name__ == "__main__":
    sys.exit(main())
