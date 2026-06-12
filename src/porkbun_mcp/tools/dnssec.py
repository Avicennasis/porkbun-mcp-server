"""DNSSEC tools.

Phase 1: get_dnssec_records (read).
Phase 3: create_dnssec_record + delete_dnssec_record (mutations + audit emit).
"""

from __future__ import annotations

from typing import Any

from .. import audit as _audit
from ..client import PorkbunClient


def get_dnssec_records_impl(client: PorkbunClient, domain: str) -> dict[str, Any]:
    return client.post(f"/dns/getDnssecRecords/{domain}")


def create_dnssec_record_impl(
    client: PorkbunClient,
    domain: str,
    *,
    key_tag: str,
    alg: str,
    digest_type: str,
    digest: str,
    max_sig_life: str | None = None,
    key_data_flags: str | None = None,
    key_data_protocol: str | None = None,
    key_data_algorithm: str | None = None,
    key_data_pub_key: str | None = None,
    reason: str,
    audit_enabled: bool = True,
) -> dict[str, Any]:
    """Publish a DNSSEC DS record at the registrar.

    Required: ``key_tag``, ``alg``, ``digest_type``, ``digest``. The
    optional ``key_data_*`` fields apply only if you're also publishing
    the underlying DNSKEY. ``reason`` is required."""
    body: dict[str, Any] = {
        "keyTag": key_tag,
        "alg": alg,
        "digestType": digest_type,
        "digest": digest,
    }
    for camel, value in (
        ("maxSigLife", max_sig_life),
        ("keyDataFlags", key_data_flags),
        ("keyDataProtocol", key_data_protocol),
        ("keyDataAlgorithm", key_data_algorithm),
        ("keyDataPubKey", key_data_pub_key),
    ):
        if value is not None:
            body[camel] = value
    out = client.post(f"/dns/createDnssecRecord/{domain}", body=body)
    _audit.emit_dns_change(
        action="DNSSEC_ADD",
        domain=domain,
        record_type="DS",
        record_name=f"keytag={key_tag}",
        reason=reason,
        alg=alg,
        digest_type=digest_type,
        enabled=audit_enabled,
    )
    return out


def delete_dnssec_record_impl(
    client: PorkbunClient,
    domain: str,
    *,
    key_tag: str,
    reason: str,
    audit_enabled: bool = True,
) -> dict[str, Any]:
    """Remove a DNSSEC DS record by key tag."""
    out = client.post(f"/dns/deleteDnssecRecord/{domain}/{key_tag}")
    _audit.emit_dns_change(
        action="DNSSEC_DELETE",
        domain=domain,
        record_type="DS",
        record_name=f"keytag={key_tag}",
        reason=reason,
        enabled=audit_enabled,
    )
    return out
