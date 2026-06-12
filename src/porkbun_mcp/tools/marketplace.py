"""Marketplace tools: browse domains for sale on the Porkbun marketplace."""

from __future__ import annotations

from typing import Any

from ..client import PorkbunClient


def get_marketplace_impl(
    client: PorkbunClient,
    *,
    start: int = 0,
    limit: int = 1000,
    query: str | None = None,
    tlds: list[str] | None = None,
    sld_length_min: int | None = None,
    sld_length_max: int | None = None,
    sort_name: str | None = None,
    sort_direction: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"start": start, "limit": limit}
    if query is not None:
        body["query"] = query
    if tlds is not None:
        body["tlds"] = tlds
    if sld_length_min is not None:
        body["sldLengthMin"] = sld_length_min
    if sld_length_max is not None:
        body["sldLengthMax"] = sld_length_max
    if sort_name is not None:
        body["sortName"] = sort_name
    if sort_direction is not None:
        body["sortDirection"] = sort_direction
    return client.post("/marketplace/getAll", body=body)
