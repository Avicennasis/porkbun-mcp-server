"""Spawn the installed ``porkbun-mcp`` console script and speak MCP to it over stdio.

This is what an MCP client actually does, so it catches what importing the module
cannot: a broken console-script entry point, a server that writes non-protocol
text to stdout, a server that dies during the handshake. It is offline -- the
handshake and ``tools/list`` never reach the Porkbun API, and the credentials are
removed from the child's environment to prove it.
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

TIMEOUT_S = 30.0
PROTOCOL_VERSION = "2025-06-18"


def _entry_point() -> str:
    beside = Path(sys.executable).parent / "porkbun-mcp"
    if beside.exists():
        return str(beside)
    found = shutil.which("porkbun-mcp")
    assert found, "porkbun-mcp console script not installed in this environment"
    return found


class _StdioPeer:
    def __init__(self, argv: list[str], env: dict[str, str]) -> None:
        self.proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
            encoding="utf-8",
        )
        self._lines: queue.Queue[str | None] = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            self._lines.put(line)
        self._lines.put(None)

    def send(self, message: dict[str, Any]) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()

    def response(self, request_id: int) -> dict[str, Any]:
        """Next message answering ``request_id``; notifications in between are skipped."""
        while True:
            try:
                line = self._lines.get(timeout=TIMEOUT_S)
            except queue.Empty:
                raise AssertionError(
                    f"no response to request {request_id} in {TIMEOUT_S}s"
                ) from None
            if line is None:
                raise AssertionError(
                    f"server closed stdout before answering {request_id}: {self.stderr()}"
                )
            message = json.loads(line)  # anything that is not JSON-RPC on stdout fails here
            if message.get("id") == request_id:
                return message

    def stderr(self) -> str:
        if self.proc.poll() is None:
            return "(server still running)"
        assert self.proc.stderr is not None
        return self.proc.stderr.read()

    def close(self) -> int:
        assert self.proc.stdin is not None
        self.proc.stdin.close()
        try:
            return self.proc.wait(timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
            raise AssertionError("server did not exit after stdin closed") from None


def test_entry_point_initializes_and_lists_tools(tmp_path: Path) -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("PORKBUN_")}
    env.update(
        PORKBUN_MCP_AUDIT_HANDLER="none",
        XDG_CACHE_HOME=str(tmp_path / "cache"),
        XDG_DATA_HOME=str(tmp_path / "data"),
    )
    peer = _StdioPeer([_entry_point()], env)
    try:
        peer.send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "porkbun-mcp-tests", "version": "0"},
                },
            }
        )
        init = peer.response(1)
        assert "error" not in init, init
        assert init["result"]["serverInfo"]["name"] == "porkbun"
        assert "tools" in init["result"]["capabilities"]

        peer.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        peer.send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        listed = peer.response(2)
        assert "error" not in listed, listed
        names = {tool["name"] for tool in listed["result"]["tools"]}
        assert {"list_dns_records", "create_dns_record", "list_domains", "ping"} <= names
        assert len(names) == len(listed["result"]["tools"])
    finally:
        rc = peer.close()
    assert rc == 0, peer.stderr()
