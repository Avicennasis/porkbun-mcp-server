"""SSL bundle retrieval — Porkbun's free DV cert downloads."""

from __future__ import annotations

from typing import Any

from ..client import PorkbunClient


def get_ssl_bundle_impl(client: PorkbunClient, domain: str) -> dict[str, Any]:
    return client.post(f"/ssl/retrieve/{domain}")
