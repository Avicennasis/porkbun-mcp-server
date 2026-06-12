"""Tests for audit emit (pluggable handler: JSONL default, external binary, none)."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

import pytest

from porkbun_mcp import audit


@pytest.fixture(autouse=True)
def _reset_handler():
    """Reset the cached handler between tests."""
    audit._handler = None
    yield
    audit._handler = None


def _capture_subprocess(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    captured: list[list[str]] = []

    def fake_run(cmd, **kw):
        captured.append(list(cmd))
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    return captured


def _set_handler(monkeypatch: pytest.MonkeyPatch, handler: str) -> None:
    monkeypatch.setenv("PORKBUN_MCP_AUDIT_HANDLER", handler)


# --- External binary handler tests ---


def test_emit_dns_change_external_handler_full_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_handler(monkeypatch, "/usr/local/bin/my-audit")
    captured = _capture_subprocess(monkeypatch)

    audit.emit_dns_change(
        action="POST",
        domain="example.com",
        record_type="A",
        record_name="web",
        reason="vhost migration",
        content="1.2.3.4",
        record_id=99,
    )

    assert len(captured) == 1
    cmd = captured[0]
    assert cmd[0] == "/usr/local/bin/my-audit"
    assert cmd[cmd.index("--source") + 1] == "porkbun-mcp"
    assert cmd[cmd.index("--category") + 1] == "dns"
    assert cmd[cmd.index("--action") + 1] == "POST"
    assert cmd[cmd.index("--service") + 1] == "example.com"
    assert cmd[cmd.index("--target") + 1] == "A `web`"
    assert cmd[cmd.index("--reason") + 1] == "vhost migration"
    payload = json.loads(cmd[cmd.index("--payload") + 1])
    assert payload == {"content": "1.2.3.4", "record_id": 99}


def test_emit_dns_change_apex_record_uses_at_sign(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_handler(monkeypatch, "/usr/local/bin/audit")
    captured = _capture_subprocess(monkeypatch)

    audit.emit_dns_change(
        action="POST",
        domain="example.com",
        record_type="MX",
        record_name="",
        reason="email setup",
        content="mail.invalid.",
        prio=10,
    )

    assert captured[0][captured[0].index("--target") + 1] == "MX `@`"


def test_emit_dns_change_record_type_none_omits_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_handler(monkeypatch, "/usr/local/bin/audit")
    captured = _capture_subprocess(monkeypatch)

    audit.emit_dns_change(
        action="DELETE",
        domain="example.com",
        record_type=None,
        record_name="",
        reason="cleanup",
        record_id=99,
    )

    assert "--target" not in captured[0]


def test_emit_dns_change_filters_empty_string_extras(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_handler(monkeypatch, "/usr/local/bin/audit")
    captured = _capture_subprocess(monkeypatch)

    audit.emit_dns_change(
        action="POST",
        domain="example.com",
        record_type="A",
        record_name="web",
        reason="r",
        empty_str="",
        none_val=None,
        good="kept",
    )

    payload = json.loads(captured[0][captured[0].index("--payload") + 1])
    assert payload == {"good": "kept"}


def test_emit_dns_change_no_payload_arg_when_all_extras_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_handler(monkeypatch, "/usr/local/bin/audit")
    captured = _capture_subprocess(monkeypatch)

    audit.emit_dns_change(
        action="DELETE",
        domain="example.com",
        record_type=None,
        record_name="",
        reason="cleanup",
        empty="",
        nothing=None,
    )

    assert "--payload" not in captured[0]


def test_emit_dns_change_disabled_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_handler(monkeypatch, "/usr/local/bin/audit")
    captured = _capture_subprocess(monkeypatch)

    audit.emit_dns_change(
        action="POST",
        domain="example.com",
        record_type="A",
        record_name="web",
        reason="r",
        enabled=False,
    )

    assert captured == []


def test_emit_dns_change_swallows_filenotfound(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_handler(monkeypatch, "/nonexistent/binary")

    def boom(cmd, **kw):
        raise FileNotFoundError("binary not installed")

    monkeypatch.setattr(subprocess, "run", boom)

    audit.emit_dns_change(
        action="POST",
        domain="example.com",
        record_type="A",
        record_name="web",
        reason="r",
    )


def test_emit_dns_change_swallows_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_handler(monkeypatch, "/usr/local/bin/audit")

    def slow(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=5)

    monkeypatch.setattr(subprocess, "run", slow)

    audit.emit_dns_change(
        action="POST",
        domain="example.com",
        record_type="A",
        record_name="web",
        reason="r",
    )


def test_emit_domain_change_external_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_handler(monkeypatch, "/usr/local/bin/audit")
    captured = _capture_subprocess(monkeypatch)

    audit.emit_domain_change(
        action="POST",
        domain="newzone.example",
        reason="adding new domain",
        ip_address="1.2.3.4",
    )

    cmd = captured[0]
    assert cmd[cmd.index("--category") + 1] == "domain"
    assert cmd[cmd.index("--service") + 1] == "newzone.example"
    assert "--target" not in cmd


def test_emit_domain_change_with_target(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_handler(monkeypatch, "/usr/local/bin/audit")
    captured = _capture_subprocess(monkeypatch)

    audit.emit_domain_change(
        action="POST",
        domain="example.com",
        reason="add label",
        target='LABEL `production`',
        color="#00ff00",
    )

    cmd = captured[0]
    assert cmd[cmd.index("--target") + 1] == "LABEL `production`"


def test_emit_domain_change_disabled_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_handler(monkeypatch, "/usr/local/bin/audit")
    captured = _capture_subprocess(monkeypatch)

    audit.emit_domain_change(
        action="POST",
        domain="newzone.example",
        reason="adding",
        enabled=False,
    )

    assert captured == []


# --- JSONL handler tests ---


def test_jsonl_handler_writes_audit_file(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setenv("XDG_DATA_HOME", tmpdir)
        _set_handler(monkeypatch, "jsonl")

        audit.emit_dns_change(
            action="POST",
            domain="example.com",
            record_type="A",
            record_name="www",
            reason="test",
        )

        audit_file = Path(tmpdir) / "porkbun-mcp" / "audit.jsonl"
        assert audit_file.exists()
        row = json.loads(audit_file.read_text().strip())
        assert row["source"] == "porkbun-mcp"
        assert row["category"] == "dns"
        assert row["action"] == "POST"
        assert row["service"] == "example.com"
        assert row["target"] == "A `www`"
        assert row["reason"] == "test"


def test_jsonl_handler_is_default(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setenv("XDG_DATA_HOME", tmpdir)
        monkeypatch.delenv("PORKBUN_MCP_AUDIT_HANDLER", raising=False)

        audit.emit_dns_change(
            action="DELETE",
            domain="example.com",
            record_type=None,
            record_name="",
            reason="cleanup",
        )

        audit_file = Path(tmpdir) / "porkbun-mcp" / "audit.jsonl"
        assert audit_file.exists()


# --- None handler test ---


def test_none_handler_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_handler(monkeypatch, "none")
    captured = _capture_subprocess(monkeypatch)

    audit.emit_dns_change(
        action="POST",
        domain="example.com",
        record_type="A",
        record_name="web",
        reason="r",
    )

    assert captured == []


# --- Action verb coverage ---


def test_emit_dns_change_action_verbs(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_handler(monkeypatch, "/usr/local/bin/audit")
    captured = _capture_subprocess(monkeypatch)

    for action in (
        "POST", "PATCH", "DELETE",
        "POST_BULK", "PATCH_BY_NAME_TYPE", "DELETE_BY_NAME_TYPE",
        "POST_FAIL", "PATCH_FAIL", "DELETE_FAIL",
    ):
        audit.emit_dns_change(
            action=action,
            domain="example.com",
            record_type="A",
            record_name="x",
            reason="r",
        )

    seen = {cmd[cmd.index("--action") + 1] for cmd in captured}
    assert seen == {
        "POST", "PATCH", "DELETE",
        "POST_BULK", "PATCH_BY_NAME_TYPE", "DELETE_BY_NAME_TYPE",
        "POST_FAIL", "PATCH_FAIL", "DELETE_FAIL",
    }
