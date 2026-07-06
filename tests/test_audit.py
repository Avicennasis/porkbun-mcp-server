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


def _capture_subprocess_full(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[list[str], bytes | None]]:
    """Like _capture_subprocess but also records the stdin input= bytes."""
    calls: list[tuple[list[str], bytes | None]] = []

    def fake_run(cmd, **kw):
        calls.append((cmd, kw.get("input")))
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


def _set_handler(monkeypatch: pytest.MonkeyPatch, handler: str) -> None:
    monkeypatch.setenv("PORKBUN_MCP_AUDIT_HANDLER", handler)


# --- External binary handler tests ---


def test_emit_dns_change_external_handler_full_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_handler(monkeypatch, "/usr/local/bin/my-audit")
    calls = _capture_subprocess_full(monkeypatch)

    audit.emit_dns_change(
        action="POST",
        domain="example.com",
        record_type="A",
        record_name="web",
        reason="vhost migration",
        content="1.2.3.4",
        record_id=99,
    )

    assert len(calls) == 1
    cmd, stdin = calls[0]
    assert cmd[0] == "/usr/local/bin/my-audit"
    assert cmd[cmd.index("--source") + 1] == "porkbun-mcp"
    assert cmd[cmd.index("--category") + 1] == "dns"
    assert cmd[cmd.index("--action") + 1] == "POST"
    assert cmd[cmd.index("--service") + 1] == "example.com"
    assert cmd[cmd.index("--target") + 1] == "A `web`"
    assert cmd[cmd.index("--reason") + 1] == "vhost migration"
    # B1-126: payload travels via stdin, argv carries only the '-' sentinel
    assert cmd[cmd.index("--payload") + 1] == "-"
    assert stdin is not None
    payload = json.loads(stdin)
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
    calls = _capture_subprocess_full(monkeypatch)

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

    _cmd, stdin = calls[0]
    assert stdin is not None
    payload = json.loads(stdin)
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
        target="LABEL `production`",
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
        "POST",
        "PATCH",
        "DELETE",
        "POST_BULK",
        "PATCH_BY_NAME_TYPE",
        "DELETE_BY_NAME_TYPE",
        "POST_FAIL",
        "PATCH_FAIL",
        "DELETE_FAIL",
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
        "POST",
        "PATCH",
        "DELETE",
        "POST_BULK",
        "PATCH_BY_NAME_TYPE",
        "DELETE_BY_NAME_TYPE",
        "POST_FAIL",
        "PATCH_FAIL",
        "DELETE_FAIL",
    }


# ---------------------------------------------------------------------------
# Failure logging (B1-127 / B1-128)
# ---------------------------------------------------------------------------


def test_external_handler_launch_failure_is_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """B1-128: a failed inkwell-emit launch must be logged, not swallowed."""
    _set_handler(monkeypatch, "/nonexistent/binary")

    def boom(cmd, **kw):
        raise FileNotFoundError("binary not installed")

    monkeypatch.setattr(subprocess, "run", boom)

    with caplog.at_level("WARNING", logger="porkbun_mcp.audit"):
        audit.emit_dns_change(
            action="POST",
            domain="example.com",
            record_type="A",
            record_name="web",
            reason="r",
        )

    assert "failed to run /nonexistent/binary" in caplog.text


def test_external_handler_nonzero_exit_is_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """B1-128: a non-zero exit from the emit binary must be logged."""
    _set_handler(monkeypatch, "/usr/local/bin/audit")

    def fail_run(cmd, **kw):
        return subprocess.CompletedProcess(args=cmd, returncode=2, stdout=b"", stderr=b"db locked")

    monkeypatch.setattr(subprocess, "run", fail_run)

    with caplog.at_level("WARNING", logger="porkbun_mcp.audit"):
        audit.emit_dns_change(
            action="POST",
            domain="example.com",
            record_type="A",
            record_name="web",
            reason="r",
        )

    assert "exited 2" in caplog.text
    assert "db locked" in caplog.text


def test_jsonl_write_failure_is_logged(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    """B1-127: JSONL write failures (disk/permissions) must be logged."""
    # Point XDG_DATA_HOME at a regular FILE so the mkdir under it raises.
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("occupied")
    monkeypatch.setenv("XDG_DATA_HOME", str(blocker))
    _set_handler(monkeypatch, "jsonl")

    with caplog.at_level("WARNING", logger="porkbun_mcp.audit"):
        audit.emit_dns_change(
            action="POST",
            domain="example.com",
            record_type="A",
            record_name="web",
            reason="r",
        )

    assert "failed to append JSONL row" in caplog.text


def test_emit_payload_travels_via_stdin_not_argv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B1-126: no argv element may contain payload JSON — only the '-' sentinel."""
    _set_handler(monkeypatch, "/usr/local/bin/audit")
    calls = _capture_subprocess_full(monkeypatch)

    audit.emit_dns_change(
        action="POST",
        domain="example.com",
        record_type="TXT",
        record_name="_acme-challenge",
        reason="cert issuance",
        content="secret-verification-token",
    )

    cmd, stdin = calls[0]
    assert cmd[cmd.index("--payload") + 1] == "-"
    assert not any("secret-verification-token" in arg for arg in cmd)
    assert stdin is not None
    assert b"secret-verification-token" in stdin


def test_emit_no_payload_means_no_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without extras there is no --payload flag and no stdin input."""
    _set_handler(monkeypatch, "/usr/local/bin/audit")
    calls = _capture_subprocess_full(monkeypatch)

    audit.emit_dns_change(
        action="DELETE",
        domain="example.com",
        record_type="A",
        record_name="web",
        reason="cleanup",
    )

    cmd, stdin = calls[0]
    assert "--payload" not in cmd
    assert stdin is None
