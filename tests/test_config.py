"""Config env-var resolution and defaults."""

from __future__ import annotations

from pathlib import Path

import pytest

from porkbun_mcp.config import DEFAULT_BASE_URL, Config


def test_config_defaults_from_empty_env(tmp_path: Path) -> None:
    cfg = Config.from_env(env={})
    assert cfg.base_url == DEFAULT_BASE_URL
    assert cfg.api_key is None
    assert cfg.secret_key is None
    assert cfg.audit_enabled is True


def test_config_credentials_from_env() -> None:
    cfg = Config.from_env(
        env={
            "PORKBUN_API_KEY": "pk1_x",
            "PORKBUN_SECRET_KEY": "sk1_x",
        }
    )
    assert cfg.api_key == "pk1_x"
    assert cfg.secret_key == "sk1_x"


def test_config_audit_disable() -> None:
    cfg = Config.from_env(env={"PORKBUN_MCP_AUDIT_ENABLED": "false"})
    assert cfg.audit_enabled is False


def test_config_require_credentials_raises_when_missing(tmp_path: Path) -> None:
    cfg = Config.from_env(env={})
    with pytest.raises(RuntimeError, match="not configured"):
        cfg.require_credentials()


def test_config_require_credentials_returns_pair() -> None:
    cfg = Config.from_env(
        env={
            "PORKBUN_API_KEY": "pk1_x",
            "PORKBUN_SECRET_KEY": "sk1_x",
        }
    )
    assert cfg.require_credentials() == ("pk1_x", "sk1_x")
