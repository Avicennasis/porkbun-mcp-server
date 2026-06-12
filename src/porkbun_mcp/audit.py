"""Pluggable audit emit for porkbun-mcp mutations.

Every mutation emits one audit row. The handler is selected via the
``PORKBUN_MCP_AUDIT_HANDLER`` environment variable:

- **unset or ``"jsonl"``** — append JSONL to
  ``~/.local/share/porkbun-mcp/audit.jsonl`` (XDG-friendly default).
- **absolute path** (e.g. ``/usr/local/bin/inkwell-emit``) — shell out
  to the given binary with ``--source``, ``--category``, ``--action``,
  ``--service``, ``--reason``, ``--target``, ``--payload`` flags.
- **``"none"``** — disable audit entirely (not recommended).

Set ``PORKBUN_MCP_AUDIT_ENABLED=false`` to disable without changing the handler.

DNS-record / DNSSEC / nameserver mutations emit ``category=dns``;
registrar-level mutations (glue records, URL forwarding, labels) emit
``category=domain``.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SOURCE = "porkbun-mcp"
CATEGORY_DNS = "dns"
CATEGORY_DOMAIN = "domain"

_handler: str | None = None


def _get_handler() -> str:
    global _handler
    if _handler is None:
        _handler = os.environ.get("PORKBUN_MCP_AUDIT_HANDLER", "jsonl")
    return _handler


def _jsonl_path() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
    p = Path(xdg) / "porkbun-mcp"
    p.mkdir(parents=True, exist_ok=True)
    return p / "audit.jsonl"


def _filter_payload(extras: dict[str, Any]) -> dict[str, Any] | None:
    cleaned = {k: v for k, v in extras.items() if v not in (None, "")}
    return cleaned or None


def _emit(
    *,
    category: str,
    action: str,
    service: str,
    target: str | None,
    reason: str,
    payload: dict[str, Any] | None,
) -> None:
    handler = _get_handler()

    if handler == "none":
        return

    if handler == "jsonl":
        row = {
            "ts": datetime.now(UTC).isoformat(),
            "source": SOURCE,
            "category": category,
            "action": action,
            "service": service,
            "target": target,
            "reason": reason,
        }
        if payload:
            row["payload"] = payload
        try:
            with open(_jsonl_path(), "a") as f:
                f.write(json.dumps(row, default=str) + "\n")
        except OSError:
            pass
        return

    # External binary handler (absolute path)
    cmd = [
        handler,
        "--source",
        SOURCE,
        "--category",
        category,
        "--action",
        action,
        "--service",
        service,
        "--reason",
        reason,
    ]
    if target:
        cmd.extend(["--target", target])
    if payload:
        cmd.extend(["--payload", json.dumps(payload, default=str)])
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run(cmd, capture_output=True, timeout=5)


def emit_dns_change(
    *,
    action: str,
    domain: str,
    record_type: str | None,
    record_name: str,
    reason: str,
    enabled: bool = True,
    **extras: Any,
) -> None:
    """Emit a DNS-record / DNSSEC / nameserver mutation row."""
    if not enabled:
        return
    if record_type is None:
        target = None
    else:
        safe_name = record_name if record_name else "@"
        target = f"{record_type} `{safe_name}`"
    _emit(
        category=CATEGORY_DNS,
        action=action,
        service=domain,
        target=target,
        reason=reason,
        payload=_filter_payload(extras),
    )


def emit_domain_change(
    *,
    action: str,
    domain: str,
    reason: str,
    target: str | None = None,
    enabled: bool = True,
    **extras: Any,
) -> None:
    """Emit a registrar-level mutation row (glue, URL forwarding, labels)."""
    if not enabled:
        return
    _emit(
        category=CATEGORY_DOMAIN,
        action=action,
        service=domain,
        target=target,
        reason=reason,
        payload=_filter_payload(extras),
    )
