"""Error classes for porkbun-mcp.

Exceptions are raised inside the client; tools convert them into structured
JSON returns (status: ERROR + message + code) rather than letting them
propagate. Per-file-ignore on N818 because some classes here are dataclass
payloads, not Python exceptions in the traditional sense.
"""

from __future__ import annotations

from dataclasses import dataclass


class PorkbunError(Exception):
    """Base for all porkbun-mcp exceptions."""


@dataclass
class PorkbunAPIError(PorkbunError):
    """Porkbun API returned a non-SUCCESS status.

    ``message`` is Porkbun's human-readable error string. ``status_code``
    is the HTTP status (often 400 for app-level errors; Porkbun returns 200
    for some failures with status:'ERROR' in the body, which we still raise).
    """

    message: str
    status_code: int = 0
    body: dict | None = None

    def __str__(self) -> str:
        return f"Porkbun API error ({self.status_code}): {self.message}"


@dataclass
class PorkbunAuthError(PorkbunAPIError):
    """API key / secret rejected. 403 from Porkbun usually means IP not allowlisted."""


@dataclass
class PorkbunRateLimit(PorkbunAPIError):
    """Porkbun rate-limited us. Client retries with backoff before raising this."""

    retry_after_seconds: float = 0.0
