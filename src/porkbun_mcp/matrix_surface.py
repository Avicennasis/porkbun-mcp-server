"""A Matrix approval surface, and the poller's entry point (#50877).

`approval_surface.py` defines the seam; this is the real transport behind it.
The room is how a human actually answers, so this is the half that turns
"the engine can hold a pending action" into "somebody can approve it".

## Why Matrix, and why the poller is a separate process

Partyline already runs a self-hosted Matrix homeserver
(`http://100.64.0.2:8298`, room `#partyline:matrix.simmons.systems`), so there
is nothing new to stand up. The fleet's existing gate —
`matrix_request_approval` + `matrix_await_approval` — is **MCP tools owned by the
agent's own session**, which is exactly why it blocks: the tool call cannot
return until a human answers. A poller is a **separate process**, so it can do
the waiting while the agent carries on. That is the whole change.

## The mapping, stated plainly

    action  ->  one message in the room, with the action id in the body
    ✅      ->  approved
    ❌      ->  denied

Reactions, not replies: a reply has to be parsed and can say anything, whereas a
reaction is a closed set the poller cannot misread. The action id is carried in
the message body and keyed to the event id on disk, so a poller restart does not
orphan requests already in the room.

## What this deliberately does not do

It does not drive anything. A poller that both asked for and acted on approval
would be able to approve its own actions. It reads decisions and hands them to
`ApprovalPoller`, which is the only thing that touches the journal.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from porkbun_mcp.approval import ActionRecord
from porkbun_mcp.approval_surface import Decision

DEFAULT_HOMESERVER = "http://100.64.0.2:8298"
DEFAULT_ROOM = "#partyline:matrix.simmons.systems"

#: The closed set of answers. Anything else is ignored rather than guessed at.
APPROVE = "✅"
DENY = "❌"
DECISIONS = {APPROVE: True, DENY: False}


def vault_get(path: str) -> str:
    """Read a secret through the fleet's lookup script.

    Shelled out rather than reimplemented: the vault is the single place these
    live, and a second reader of it is a second thing to get wrong.
    """
    import subprocess

    out = subprocess.run(  # noqa: S603
        ["/opt/simsyssecrets/scripts/lookup.sh", path],  # noqa: S607
        capture_output=True,
        check=True,
        text=True,
    )
    return out.stdout.strip()


class MatrixHttpClient:
    """The minimum Matrix client-server API a surface needs.

    Two calls, both plain HTTP: send an `m.room.message`, and read the
    `m.annotation` relations on one event. No SDK, so no dependency — and no
    state beyond a token, which keeps the poller easy to restart.
    """

    def __init__(self, homeserver: str, token: str) -> None:
        self._hs = homeserver.rstrip("/")
        self._token = token

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        url = f"{self._hs}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(  # noqa: S310
            url,
            data=data,
            headers={"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"},
            method=method,
        )
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            return json.loads(resp.read().decode())

    def send(self, room: str, body: str) -> str:
        """Send a message, returning its event id."""
        quoted = urllib.parse.quote(room, safe="")
        txn = os.urandom(8).hex()
        out = self._request(
            "PUT",
            f"/_matrix/client/v3/rooms/{quoted}/send/m.room.message/{txn}",
            {"msgtype": "m.text", "body": body},
        )
        return str(out["event_id"])

    def reactions(self, room: str, event_id: str) -> list[str]:
        """Every reaction key on an event, in the order Matrix returns them."""
        quoted_room = urllib.parse.quote(room, safe="")
        quoted_ev = urllib.parse.quote(event_id, safe="")
        out = self._request(
            "GET",
            f"/_matrix/client/v3/rooms/{quoted_room}/relations/{quoted_ev}/m.annotation/m.reaction",
        )
        keys = []
        for chunk in out.get("chunk", []):
            key = (chunk.get("content") or {}).get("m.relates_to", {}).get("key")
            if key:
                keys.append(str(key))
        return keys


class MatrixApprovalSurface:
    """An `ApprovalSurface` backed by a Matrix room.

    `request()` sends; `poll()` reads reactions. **Neither blocks**, which is
    the property the whole design rests on.

    The action-id → event-id map is on disk because the poller may restart
    between posting a request and reading its answer, and a request whose event
    id was only in memory would become unanswerable.
    """

    def __init__(self, client: MatrixHttpClient, room: str, state_path: Path) -> None:
        self._client = client
        self._room = room
        self._state = state_path

    def _load(self) -> dict[int, str]:
        if not self._state.exists():
            return {}
        return {int(k): v for k, v in json.loads(self._state.read_text(encoding="utf-8")).items()}

    def _save(self, mapping: dict[int, str]) -> None:
        self._state.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._state.with_suffix(self._state.suffix + ".tmp")
        tmp.write_text(json.dumps({str(k): v for k, v in mapping.items()}), encoding="utf-8")
        os.replace(tmp, self._state)

    def request(self, record: ActionRecord, *, summary: str) -> None:
        body = (
            f"Approval needed — {summary}\n"
            f"React {APPROVE} to approve, {DENY} to deny.\n"
            f"(action {record.id})"
        )
        event_id = self._client.send(self._room, body)
        mapping = self._load()
        mapping[record.id] = event_id
        self._save(mapping)

    def poll(self) -> list[Decision]:
        mapping = self._load()
        out: list[Decision] = []
        still: dict[int, str] = {}
        for action_id, event_id in mapping.items():
            try:
                keys = self._client.reactions(self._room, event_id)
            except Exception:  # noqa: BLE001 - a read failure must not lose a request
                still[action_id] = event_id
                continue
            answer = next((DECISIONS[k] for k in keys if k in DECISIONS), None)
            if answer is None:
                still[action_id] = event_id
                continue
            out.append(Decision(action_id=action_id, approved=answer, by="matrix"))
            # Answered: drop it, so the same reaction is never read twice. That
            # would be a second provider call for one decision.
        if still != mapping:
            self._save(still)
        return out


def build_surface(
    *,
    token_path: str = "partyline.admin_access_token",
    homeserver: str | None = None,
    room: str | None = None,
    state_path: Path | None = None,
) -> MatrixApprovalSurface:
    """Wire the real thing. Credentials come from the vault, never from a file."""
    client = MatrixHttpClient(
        homeserver or os.environ.get("APPROVAL_MATRIX_HOMESERVER", DEFAULT_HOMESERVER),
        vault_get(token_path),
    )
    return MatrixApprovalSurface(
        client,
        room or os.environ.get("APPROVAL_MATRIX_ROOM", DEFAULT_ROOM),
        state_path
        or Path(
            os.environ.get(
                "APPROVAL_STATE",
                str(Path.home() / ".local/state/porkbun-mcp/approval-events.json"),
            )
        ),
    )
