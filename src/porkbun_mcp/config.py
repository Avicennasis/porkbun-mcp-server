"""Environment-variable configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass

from . import secrets

DEFAULT_BASE_URL = "https://api.porkbun.com/api/json/v3"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_LOG_LEVEL = "INFO"


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    base_url: str = DEFAULT_BASE_URL
    api_key: str | None = None
    secret_key: str | None = None
    audit_enabled: bool = True
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    log_level: str = DEFAULT_LOG_LEVEL

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Config:
        e = dict(env if env is not None else os.environ)
        api_key, secret_key = secrets.load_credentials(env=e)

        return cls(
            base_url=e.get("PORKBUN_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
            api_key=api_key,
            secret_key=secret_key,
            audit_enabled=_truthy(e.get("PORKBUN_MCP_AUDIT_ENABLED", "true")),
            timeout_seconds=float(e.get("PORKBUN_MCP_TIMEOUT", DEFAULT_TIMEOUT_SECONDS)),
            log_level=e.get("PORKBUN_MCP_LOG_LEVEL", DEFAULT_LOG_LEVEL).upper(),
        )

    def require_credentials(self) -> tuple[str, str]:
        if not self.api_key or not self.secret_key:
            raise RuntimeError(
                "Porkbun credentials not configured. Set PORKBUN_API_KEY + "
                "PORKBUN_SECRET_KEY env vars."
            )
        return self.api_key, self.secret_key
