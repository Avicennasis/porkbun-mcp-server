"""httpx-based Porkbun API v3 wrapper.

Porkbun's API is unusual: every endpoint is POST with a JSON body that
includes the API key and secret. We inject those into every request body
so callers only think about the per-call payload.

Retries: Porkbun's published rate limit is generous and rarely hit, but on
a 429 we retry with exponential backoff capped at ``max_retries`` and
honor the ``Retry-After`` header when present.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from .errors import (
    PorkbunAPIError,
    PorkbunAuthError,
    PorkbunRateLimit,
)

log = logging.getLogger("porkbun_mcp.client")

DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BASE_SECONDS = 0.5
DEFAULT_TIMEOUT = 30.0


class PorkbunClient:
    """Synchronous httpx wrapper. One instance per server lifetime."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        secret_key: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_base_seconds: float = DEFAULT_RETRY_BASE_SECONDS,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._secret_key = secret_key
        self._max_retries = max_retries
        self._retry_base = retry_base_seconds
        self._http = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            transport=transport,
            headers={"User-Agent": "porkbun-mcp/0.1"},
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> PorkbunClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def post(
        self,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        idempotent: bool = False,
    ) -> dict[str, Any]:
        """POST to ``path`` with creds + ``body`` merged into the JSON payload.

        ``idempotent=True`` marks read-style endpoints: transient upstream
        errors (502/503/504) are retried with backoff for those calls only.
        Mutations keep the default (no 5xx retry) so an operation that may
        already have been applied behind a failing gateway is never
        double-applied.
        """
        payload: dict[str, Any] = {
            "apikey": self._api_key,
            "secretapikey": self._secret_key,
        }
        if body:
            payload.update(body)

        last_retry_after = 0.0
        for attempt in range(self._max_retries):
            try:
                resp = self._http.post(path, json=payload)
            except httpx.HTTPError as e:
                # B1-123: network-level failures (ConnectError, ReadTimeout,
                # ...) must surface as PorkbunError so the tool layer's
                # `except PorkbunError` catches them.
                raise PorkbunAPIError(
                    message=f"Network error calling Porkbun ({e.__class__.__name__}): {e}",
                    status_code=0,
                ) from e
            if resp.status_code == 429:
                retry_after = self._parse_retry_after(resp)
                last_retry_after = retry_after
                log.warning(
                    "porkbun 429; sleeping %.2fs (attempt %d/%d)",
                    retry_after,
                    attempt + 1,
                    self._max_retries,
                )
                time.sleep(max(retry_after, self._retry_base * (2**attempt)))
                continue
            if (
                idempotent
                and resp.status_code in (502, 503, 504)
                and attempt < self._max_retries - 1
            ):
                # B1-124: transient upstream errors on idempotent reads get
                # backoff retries; the final attempt falls through so the
                # 5xx surfaces as a normal PorkbunAPIError.
                delay = self._retry_base * (2**attempt)
                log.warning(
                    "porkbun %d on idempotent call; retrying in %.2fs (attempt %d/%d)",
                    resp.status_code,
                    delay,
                    attempt + 1,
                    self._max_retries,
                )
                time.sleep(delay)
                continue
            return self._handle_response(resp)

        raise PorkbunRateLimit(
            message="Rate limit exceeded after retries",
            status_code=429,
            # B1-125: surface the last known Retry-After instead of 0.0 so
            # callers can schedule a sensible retry.
            retry_after_seconds=last_retry_after,
        )

    @staticmethod
    def _parse_retry_after(resp: httpx.Response) -> float:
        raw = resp.headers.get("Retry-After")
        if not raw:
            return 0.0
        try:
            return float(raw)
        except ValueError:
            return 0.0

    def _handle_response(self, resp: httpx.Response) -> dict[str, Any]:
        try:
            data = resp.json()
        except ValueError:
            raise PorkbunAPIError(
                message=f"Non-JSON response: {resp.text[:200]!r}",
                status_code=resp.status_code,
            ) from None

        if resp.status_code == 403:
            raise PorkbunAuthError(
                message=data.get("message", "Auth rejected"),
                status_code=403,
                body=data,
            )

        if resp.status_code >= 400 or data.get("status") == "ERROR":
            raise PorkbunAPIError(
                message=data.get("message", f"HTTP {resp.status_code}"),
                status_code=resp.status_code,
                body=data,
            )

        return data
