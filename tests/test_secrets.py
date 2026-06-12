"""Tests for env-var credential loading."""

from __future__ import annotations

from porkbun_mcp.secrets import load_credentials


def test_load_credentials_from_env() -> None:
    api_key, secret_key = load_credentials(
        env={
            "PORKBUN_API_KEY": "pk1_x",
            "PORKBUN_SECRET_KEY": "sk1_x",
        }
    )
    assert api_key == "pk1_x"
    assert secret_key == "sk1_x"


def test_load_credentials_returns_none_when_unset() -> None:
    assert load_credentials(env={}) == (None, None)


def test_load_credentials_partial_api_key_only() -> None:
    api_key, secret_key = load_credentials(env={"PORKBUN_API_KEY": "pk1_x"})
    assert api_key == "pk1_x"
    assert secret_key is None


def test_load_credentials_partial_secret_key_only() -> None:
    api_key, secret_key = load_credentials(env={"PORKBUN_SECRET_KEY": "sk1_x"})
    assert api_key is None
    assert secret_key == "sk1_x"


def test_load_credentials_strips_whitespace() -> None:
    api_key, secret_key = load_credentials(
        env={
            "PORKBUN_API_KEY": "  pk1_x  ",
            "PORKBUN_SECRET_KEY": "  sk1_x  ",
        }
    )
    assert api_key == "pk1_x"
    assert secret_key == "sk1_x"


def test_secrets_file_param_ignored() -> None:
    """The secrets_file param is kept for back-compat but has no effect."""
    api_key, secret_key = load_credentials(
        secrets_file="/nonexistent",
        env={"PORKBUN_API_KEY": "pk1_x", "PORKBUN_SECRET_KEY": "sk1_x"},
    )
    assert api_key == "pk1_x"
    assert secret_key == "sk1_x"
