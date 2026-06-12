"""Load Porkbun API credentials from environment variables.

Resolves credentials from env vars:
  - ``PORKBUN_API_KEY`` (pk1_...)
  - ``PORKBUN_SECRET_KEY`` (sk1_...)

Both must be set for authentication to succeed.
"""

from __future__ import annotations

import os


def load_credentials(
    secrets_file: object = None,
    *,
    env: dict[str, str] | None = None,
) -> tuple[str | None, str | None]:
    """Resolve Porkbun (api_key, secret_key) from environment.

    The ``secrets_file`` parameter is accepted for back-compat but ignored.
    """
    e = env if env is not None else os.environ
    api_key = e.get("PORKBUN_API_KEY")
    secret_key = e.get("PORKBUN_SECRET_KEY")
    return (
        api_key.strip() if api_key else None,
        secret_key.strip() if secret_key else None,
    )
