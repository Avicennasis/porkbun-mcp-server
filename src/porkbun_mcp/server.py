"""FastMCP entrypoint for porkbun-mcp.

Note: this module deliberately does NOT use ``from __future__ import
annotations``. FastMCP's @mcp.tool() decorator runs ``issubclass`` against
parameter annotations to detect Context params; under PEP 563 every
annotation becomes a string and that raises TypeError. Same constraint
documented in redmine-mcp/src/redmine_mcp/server.py.
"""

import logging
import sys

from mcp.server.fastmcp import FastMCP

from .client import PorkbunClient
from .config import Config
from .errors import PorkbunError
from .tools import account, dns, dnssec, domains, marketplace, nameservers, ssl

log = logging.getLogger("porkbun_mcp")

mcp = FastMCP(
    "porkbun",
    instructions=(
        "Porkbun MCP server. Full coverage of API v3: domains, DNS records, "
        "DNSSEC, SSL bundle retrieval, glue records, URL forwarding, labels, "
        "domain registration/renewal/transfers, marketplace, account management, "
        "email hosting, and API key management. "
        "Every mutation tool requires a `reason` argument and emits an audit row "
        "(source='porkbun-mcp', category='dns' for DNS/DNSSEC/NS, "
        "category='domain' for glue/forwarding/labels/registration/renewal/transfers)."
    ),
)

_config: Config | None = None
_client: PorkbunClient | None = None


def _get_config() -> Config:
    global _config
    if _config is None:
        _config = Config.from_env()
        logging.basicConfig(
            level=getattr(logging, _config.log_level, logging.INFO),
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
            stream=sys.stderr,
        )
    return _config


def _get_client() -> PorkbunClient:
    global _client
    if _client is None:
        cfg = _get_config()
        api_key, secret_key = cfg.require_credentials()
        _client = PorkbunClient(
            base_url=cfg.base_url,
            api_key=api_key,
            secret_key=secret_key,
            timeout=cfg.timeout_seconds,
        )
    return _client


def _wrap_error(err: Exception) -> dict:
    """Convert a PorkbunError into a structured tool response."""
    return {
        "status": "ERROR",
        "error_class": type(err).__name__,
        "message": str(err),
    }


# ---------------------------------------------------------------------------
# Account / meta tools
# ---------------------------------------------------------------------------


@mcp.tool()
def ping() -> dict:
    """Authenticated ping against Porkbun. Returns {"status", "yourIp"}.
    Useful as a readiness probe — confirms credentials work and your
    public IP is on Porkbun's allowlist (if you've enabled IP restriction).
    """
    try:
        return account.ping_impl(_get_client())
    except PorkbunError as e:
        return _wrap_error(e)


@mcp.tool()
def get_pricing(force_refresh: bool = False) -> dict:
    """Public TLD pricing table from Porkbun. Served from a disk cache
    (~/.cache/porkbun-mcp/pricing.json, XDG-aware) with a 24h TTL
    (override via PORKBUN_PRICING_CACHE_TTL, seconds).
    ``force_refresh=True`` bypasses the cache and refetches live."""
    try:
        return account.get_pricing_impl(_get_client(), force_refresh=force_refresh)
    except PorkbunError as e:
        return _wrap_error(e)


@mcp.tool()
def get_account_balance() -> dict:
    """Current Porkbun account credit balance."""
    try:
        return account.get_account_balance_impl(_get_client())
    except PorkbunError as e:
        return _wrap_error(e)


@mcp.tool()
def check_availability(domain: str) -> dict:
    """Check whether ``domain`` (e.g. 'example.com') is available for registration."""
    try:
        return account.check_availability_impl(_get_client(), domain)
    except PorkbunError as e:
        return _wrap_error(e)


@mcp.tool()
def check_bulk_availability(domains: list[str]) -> dict:
    """Check availability for multiple domains. Client-side fan-out — one
    API call per domain. Per-domain errors surface in the results map
    without aborting the batch."""
    try:
        return account.check_bulk_availability_impl(_get_client(), domains)
    except PorkbunError as e:
        return _wrap_error(e)


@mcp.tool()
def get_pricing_for_tld(tld: str, force_refresh: bool = False) -> dict:
    """Pricing for a single TLD (e.g. 'com'). Derived from the same
    cached pricing table as ``get_pricing`` — no separate API call.
    ``force_refresh=True`` bypasses the cache."""
    try:
        return account.get_pricing_for_tld_impl(_get_client(), tld, force_refresh=force_refresh)
    except PorkbunError as e:
        return _wrap_error(e)


@mcp.tool()
def list_supported_tlds(force_refresh: bool = False) -> dict:
    """All TLDs Porkbun supports for registration. Sorted alphabetically.
    Derived from the same cached pricing table as ``get_pricing``.
    ``force_refresh=True`` bypasses the cache."""
    try:
        return account.list_supported_tlds_impl(_get_client(), force_refresh=force_refresh)
    except PorkbunError as e:
        return _wrap_error(e)


@mcp.tool()
def get_api_settings() -> dict:
    """Get the account's API spend control settings and current month's
    spend total. All amounts are in cents."""
    try:
        return account.get_api_settings_impl(_get_client())
    except PorkbunError as e:
        return _wrap_error(e)


@mcp.tool()
def get_ip() -> dict:
    """Get the caller's public IP address. No authentication required
    (though our client always sends credentials, which is harmless).
    Similar to ``ping`` but without credential verification."""
    try:
        return account.get_ip_impl(_get_client())
    except PorkbunError as e:
        return _wrap_error(e)


@mcp.tool()
def create_invite(email: str | None = None, return_url: str | None = None) -> dict:
    """Create a one-time account registration invite. The invite expires
    in 48 hours. ``email`` pre-fills the registration form. ``return_url``
    redirects the user after registration."""
    try:
        return account.create_invite_impl(
            _get_client(),
            email=email,
            return_url=return_url,
        )
    except PorkbunError as e:
        return _wrap_error(e)


@mcp.tool()
def get_invite_status(token: str) -> dict:
    """Check the status of a registration invite. Returns PENDING,
    ACCEPTED (with ``newAccountId``), or EXPIRED."""
    try:
        return account.get_invite_status_impl(_get_client(), token)
    except PorkbunError as e:
        return _wrap_error(e)


@mcp.tool()
def set_email_password(email_address: str, password: str) -> dict:
    """Set the password for an email hosting account. ``email_address``
    is the full address (e.g. user@example.com)."""
    try:
        return account.set_email_password_impl(
            _get_client(),
            email_address=email_address,
            password=password,
        )
    except PorkbunError as e:
        return _wrap_error(e)


@mcp.tool()
def request_api_key(name: str | None = None) -> dict:
    """Initiate an API key authorization request. Returns a
    ``requestToken`` and ``authUrl`` for the account holder to approve.
    ``name`` is an optional human-readable label for the application."""
    try:
        return account.request_api_key_impl(_get_client(), name=name)
    except PorkbunError as e:
        return _wrap_error(e)


@mcp.tool()
def retrieve_api_key(request_token: str) -> dict:
    """Poll to check whether an API key authorization request has been
    approved. Returns PENDING while awaiting approval, or the public
    API key on approval."""
    try:
        return account.retrieve_api_key_impl(
            _get_client(),
            request_token=request_token,
        )
    except PorkbunError as e:
        return _wrap_error(e)


@mcp.tool()
def get_marketplace(
    start: int = 0,
    limit: int = 1000,
    query: str | None = None,
    tlds: list[str] | None = None,
    sld_length_min: int | None = None,
    sld_length_max: int | None = None,
    sort_name: str | None = None,
    sort_direction: str | None = None,
) -> dict:
    """Browse domains listed for sale on the Porkbun marketplace.
    Supports pagination (``start``/``limit``), search (``query``),
    TLD filtering, SLD length filtering, and sorting."""
    try:
        return marketplace.get_marketplace_impl(
            _get_client(),
            start=start,
            limit=limit,
            query=query,
            tlds=tlds,
            sld_length_min=sld_length_min,
            sld_length_max=sld_length_max,
            sort_name=sort_name,
            sort_direction=sort_direction,
        )
    except PorkbunError as e:
        return _wrap_error(e)


# ---------------------------------------------------------------------------
# Domain inventory + URL forwarding + labels (read)
# ---------------------------------------------------------------------------


@mcp.tool()
def list_domains(start: int = 0, include_labels: bool = False) -> dict:
    """List all domains in the Porkbun account. ``start`` is a 0-indexed
    offset for pagination (Porkbun returns 1000 per page)."""
    try:
        return domains.list_domains_impl(_get_client(), start=start, include_labels=include_labels)
    except PorkbunError as e:
        return _wrap_error(e)


@mcp.tool()
def get_url_forwarding(domain: str) -> dict:
    """List URL-forwarding rules for ``domain``."""
    try:
        return domains.get_url_forwarding_impl(_get_client(), domain)
    except PorkbunError as e:
        return _wrap_error(e)


@mcp.tool()
def get_domain(domain: str) -> dict:
    """Get detailed info for a single domain — expiry date, status, auto-renew
    setting, creation date, lock state, etc."""
    try:
        return domains.get_domain_impl(_get_client(), domain)
    except PorkbunError as e:
        return _wrap_error(e)


@mcp.tool()
def get_glue(domain: str) -> dict:
    """List glue records (host A/AAAA records at the registrar) for ``domain``.
    Returns an empty list if no glue records exist."""
    try:
        return domains.get_glue_impl(_get_client(), domain)
    except PorkbunError as e:
        return _wrap_error(e)


@mcp.tool()
def list_labels() -> dict:
    """List all domain labels (Porkbun's tagging system)."""
    try:
        return domains.list_labels_impl(_get_client())
    except PorkbunError as e:
        return _wrap_error(e)


# ---------------------------------------------------------------------------
# Domain registration / renewal / transfer
# ---------------------------------------------------------------------------


@mcp.tool()
def register_domain(domain: str, cost: int, reason: str, agree_to_terms: str = "yes") -> dict:
    """Register a new domain using account credit. ``cost`` is in pennies
    (USD cents) and must exactly match the price from ``check_availability``.
    ``agree_to_terms`` must be ``'yes'`` or ``'1'``. This is a financial
    operation — verify cost before calling. action=REGISTER."""
    try:
        cfg = _get_config()
        return domains.register_domain_impl(
            _get_client(),
            domain,
            cost=cost,
            agree_to_terms=agree_to_terms,
            reason=reason,
            audit_enabled=cfg.audit_enabled,
        )
    except PorkbunError as e:
        return _wrap_error(e)


@mcp.tool()
def renew_domain(domain: str, cost: int, reason: str) -> dict:
    """Renew a domain using account credit. ``cost`` is in pennies (USD
    cents) and must exactly match the renewal price. Use
    ``check_availability`` with the domain to get the current price
    before renewing. This is a financial operation. action=RENEW."""
    try:
        cfg = _get_config()
        return domains.renew_domain_impl(
            _get_client(),
            domain,
            cost=cost,
            reason=reason,
            audit_enabled=cfg.audit_enabled,
        )
    except PorkbunError as e:
        return _wrap_error(e)


@mcp.tool()
def transfer_domain(domain: str, auth_code: str, cost: int, reason: str) -> dict:
    """Initiate an inbound domain transfer. ``auth_code`` is the EPP
    authorization code from the current registrar. ``cost`` is in pennies
    and must match the transfer price. Transfers take 5–7 days.
    This is a financial operation. action=TRANSFER."""
    try:
        cfg = _get_config()
        return domains.transfer_domain_impl(
            _get_client(),
            domain,
            auth_code=auth_code,
            cost=cost,
            reason=reason,
            audit_enabled=cfg.audit_enabled,
        )
    except PorkbunError as e:
        return _wrap_error(e)


@mcp.tool()
def get_transfer_status(domain: str) -> dict:
    """Get the most recent transfer record for ``domain``."""
    try:
        return domains.get_transfer_status_impl(_get_client(), domain)
    except PorkbunError as e:
        return _wrap_error(e)


@mcp.tool()
def list_transfers() -> dict:
    """List all active inbound domain transfers (excludes completed and
    canceled transfers)."""
    try:
        return domains.list_transfers_impl(_get_client())
    except PorkbunError as e:
        return _wrap_error(e)


# ---------------------------------------------------------------------------
# Registrar mutations (category=domain)
# ---------------------------------------------------------------------------


@mcp.tool()
def update_auto_renew(domain: str, auto_renew: bool, reason: str) -> dict:
    """Toggle auto-renewal for ``domain``. ``auto_renew=True`` enables,
    ``False`` disables. ``reason`` is required; audit row action=AUTO_RENEW."""
    try:
        cfg = _get_config()
        return domains.update_auto_renew_impl(
            _get_client(),
            domain,
            auto_renew=auto_renew,
            reason=reason,
            audit_enabled=cfg.audit_enabled,
        )
    except PorkbunError as e:
        return _wrap_error(e)


@mcp.tool()
def create_glue(domain: str, host: str, ips: list[str], reason: str) -> dict:
    """Create a glue record (host A/AAAA records served by the registrar).
    Required for custom nameservers like ns1.example.com that point at
    IPs you control. ``reason`` is required; audit row action=GLUE_CREATE."""
    try:
        cfg = _get_config()
        return domains.create_glue_impl(
            _get_client(),
            domain,
            host=host,
            ips=ips,
            reason=reason,
            audit_enabled=cfg.audit_enabled,
        )
    except PorkbunError as e:
        return _wrap_error(e)


@mcp.tool()
def update_glue(domain: str, host: str, ips: list[str], reason: str) -> dict:
    """Replace the IPs on an existing glue record. action=GLUE_UPDATE."""
    try:
        cfg = _get_config()
        return domains.update_glue_impl(
            _get_client(),
            domain,
            host=host,
            ips=ips,
            reason=reason,
            audit_enabled=cfg.audit_enabled,
        )
    except PorkbunError as e:
        return _wrap_error(e)


@mcp.tool()
def delete_glue(domain: str, host: str, reason: str) -> dict:
    """Remove a glue record by host name. action=GLUE_DELETE."""
    try:
        cfg = _get_config()
        return domains.delete_glue_impl(
            _get_client(),
            domain,
            host=host,
            reason=reason,
            audit_enabled=cfg.audit_enabled,
        )
    except PorkbunError as e:
        return _wrap_error(e)


@mcp.tool()
def add_url_forward(
    domain: str,
    subdomain: str,
    location: str,
    reason: str,
    type: str = "permanent",
    include_path: str = "no",
    wildcard: str = "no",
) -> dict:
    """Add a URL forward. ``type`` is 'permanent' (301) or 'temporary' (302).
    ``include_path`` and ``wildcard`` are 'yes' / 'no' Porkbun flags.
    ``subdomain=""`` forwards the apex. action=URLFWD_ADD."""
    try:
        cfg = _get_config()
        return domains.add_url_forward_impl(
            _get_client(),
            domain,
            subdomain=subdomain,
            location=location,
            type=type,
            include_path=include_path,
            wildcard=wildcard,
            reason=reason,
            audit_enabled=cfg.audit_enabled,
        )
    except PorkbunError as e:
        return _wrap_error(e)


@mcp.tool()
def delete_url_forward(domain: str, record_id: str, reason: str) -> dict:
    """Remove a URL forward by record id (from get_url_forwarding).
    action=URLFWD_DELETE."""
    try:
        cfg = _get_config()
        return domains.delete_url_forward_impl(
            _get_client(),
            domain,
            record_id,
            reason=reason,
            audit_enabled=cfg.audit_enabled,
        )
    except PorkbunError as e:
        return _wrap_error(e)


@mcp.tool()
def add_label(domain: str, label_name: str, color: str, reason: str) -> dict:
    """Create a Porkbun label and attach it to ``domain``. ``color`` is a
    Porkbun-defined color name (orange, red, blue, ...). Returns
    ``{"status": "SUCCESS", "id": <int>}``. action=LABEL_ADD."""
    try:
        cfg = _get_config()
        return domains.add_label_impl(
            _get_client(),
            domain,
            label_name=label_name,
            color=color,
            reason=reason,
            audit_enabled=cfg.audit_enabled,
        )
    except PorkbunError as e:
        return _wrap_error(e)


@mcp.tool()
def remove_label(domain: str, label_id: str, reason: str) -> dict:
    """Detach a label from ``domain`` by label id. action=LABEL_DELETE."""
    try:
        cfg = _get_config()
        return domains.remove_label_impl(
            _get_client(),
            domain,
            label_id,
            reason=reason,
            audit_enabled=cfg.audit_enabled,
        )
    except PorkbunError as e:
        return _wrap_error(e)


# ---------------------------------------------------------------------------
# Nameserver read
# ---------------------------------------------------------------------------


@mcp.tool()
def get_name_servers(domain: str) -> dict:
    """Get the active nameservers for ``domain``."""
    try:
        return nameservers.get_name_servers_impl(_get_client(), domain)
    except PorkbunError as e:
        return _wrap_error(e)


@mcp.tool()
def update_name_servers(domain: str, ns: list[str], reason: str) -> dict:
    """Replace ``domain``'s nameservers. ``ns`` is the new list of NS
    hostnames (typically 2-4). ``reason`` is required and tags the
    audit row (action='NS', new list goes in the payload column)."""
    try:
        cfg = _get_config()
        return nameservers.update_name_servers_impl(
            _get_client(),
            domain,
            ns=ns,
            reason=reason,
            audit_enabled=cfg.audit_enabled,
        )
    except PorkbunError as e:
        return _wrap_error(e)


# ---------------------------------------------------------------------------
# DNS record reads
# ---------------------------------------------------------------------------


@mcp.tool()
def list_dns_records(domain: str) -> dict:
    """List ALL DNS records for ``domain`` from Porkbun's nameservers.
    Note: if the domain's NS is set to a non-Porkbun host, these records
    are not what resolvers see — they're what Porkbun has on file."""
    try:
        return dns.list_dns_records_impl(_get_client(), domain)
    except PorkbunError as e:
        return _wrap_error(e)


@mcp.tool()
def get_dns_record(domain: str, record_id: str) -> dict:
    """Fetch a single DNS record by Porkbun's record id."""
    try:
        return dns.get_dns_record_impl(_get_client(), domain, record_id)
    except PorkbunError as e:
        return _wrap_error(e)


@mcp.tool()
def get_dns_records_by_name_type(domain: str, type: str, subdomain: str = "") -> dict:
    """Filter DNS records by type ('A','TXT','MX',...) and subdomain
    (empty string for apex). Useful for checking whether a specific record
    exists without scanning the full zone."""
    try:
        return dns.get_dns_records_by_name_type_impl(_get_client(), domain, type, subdomain)
    except PorkbunError as e:
        return _wrap_error(e)


# ---------------------------------------------------------------------------
# DNS record mutations (Phase 2)
# ---------------------------------------------------------------------------


@mcp.tool()
def create_dns_record(
    domain: str,
    type: str,
    name: str,
    content: str,
    reason: str,
    ttl: int = 600,
    prio: int | None = None,
    notes: str | None = None,
) -> dict:
    """Create a DNS record on ``domain``. ``name`` is the subdomain
    ("" for apex). ``reason`` is required and goes into the audit row.
    Returns ``{"status": "SUCCESS", "id": <int>}`` on success."""
    try:
        cfg = _get_config()
        return dns.create_dns_record_impl(
            _get_client(),
            domain,
            type=type,
            name=name,
            content=content,
            ttl=ttl,
            prio=prio,
            notes=notes,
            reason=reason,
            audit_enabled=cfg.audit_enabled,
        )
    except PorkbunError as e:
        return _wrap_error(e)


@mcp.tool()
def edit_dns_record(
    domain: str,
    record_id: str,
    type: str,
    name: str,
    content: str,
    reason: str,
    ttl: int = 600,
    prio: int | None = None,
    notes: str | None = None,
) -> dict:
    """Edit an existing DNS record by Porkbun's record id. Porkbun's
    edit is a full replace — pass every field. ``reason`` is required.
    """
    try:
        cfg = _get_config()
        return dns.edit_dns_record_impl(
            _get_client(),
            domain,
            record_id,
            type=type,
            name=name,
            content=content,
            ttl=ttl,
            prio=prio,
            notes=notes,
            reason=reason,
            audit_enabled=cfg.audit_enabled,
        )
    except PorkbunError as e:
        return _wrap_error(e)


@mcp.tool()
def edit_dns_records_by_name_type(
    domain: str,
    type: str,
    subdomain: str,
    content: str,
    reason: str,
    ttl: int = 600,
    prio: int | None = None,
    notes: str | None = None,
) -> dict:
    """Bulk-edit every record matching (type, subdomain) on ``domain``.
    ``subdomain="" → apex. ``reason`` is required."""
    try:
        cfg = _get_config()
        return dns.edit_dns_records_by_name_type_impl(
            _get_client(),
            domain,
            type=type,
            subdomain=subdomain,
            content=content,
            ttl=ttl,
            prio=prio,
            notes=notes,
            reason=reason,
            audit_enabled=cfg.audit_enabled,
        )
    except PorkbunError as e:
        return _wrap_error(e)


@mcp.tool()
def delete_dns_record(domain: str, record_id: str, reason: str) -> dict:
    """Delete a DNS record by Porkbun's record id. ``reason`` is required."""
    try:
        cfg = _get_config()
        return dns.delete_dns_record_impl(
            _get_client(),
            domain,
            record_id,
            reason=reason,
            audit_enabled=cfg.audit_enabled,
        )
    except PorkbunError as e:
        return _wrap_error(e)


@mcp.tool()
def delete_dns_records_by_name_type(domain: str, type: str, subdomain: str, reason: str) -> dict:
    """Bulk-delete every record matching (type, subdomain) on ``domain``.
    ``subdomain="" → apex. ``reason`` is required."""
    try:
        cfg = _get_config()
        return dns.delete_dns_records_by_name_type_impl(
            _get_client(),
            domain,
            type=type,
            subdomain=subdomain,
            reason=reason,
            audit_enabled=cfg.audit_enabled,
        )
    except PorkbunError as e:
        return _wrap_error(e)


@mcp.tool()
def bulk_create_dns_records(domain: str, records: list[dict], reason: str) -> dict:
    """Create multiple DNS records on ``domain``. Porkbun has no native
    bulk endpoint — this fans out one create per record with
    continue-and-report semantics: failures collect in ``failed``,
    successes in ``created``. Each entry needs ``type`` / ``name`` /
    ``content``; ``ttl`` / ``prio`` / ``notes`` are optional. ``reason``
    is required and tags every per-record audit row."""
    try:
        cfg = _get_config()
        return dns.bulk_create_dns_records_impl(
            _get_client(),
            domain,
            records,
            reason=reason,
            audit_enabled=cfg.audit_enabled,
        )
    except PorkbunError as e:
        return _wrap_error(e)


# ---------------------------------------------------------------------------
# DNSSEC + SSL reads
# ---------------------------------------------------------------------------


@mcp.tool()
def get_dnssec_records(domain: str) -> dict:
    """List the DS records Porkbun publishes for ``domain``. Empty if DNSSEC
    is not enabled for the zone."""
    try:
        return dnssec.get_dnssec_records_impl(_get_client(), domain)
    except PorkbunError as e:
        return _wrap_error(e)


@mcp.tool()
def create_dnssec_record(
    domain: str,
    key_tag: str,
    alg: str,
    digest_type: str,
    digest: str,
    reason: str,
    max_sig_life: str | None = None,
    key_data_flags: str | None = None,
    key_data_protocol: str | None = None,
    key_data_algorithm: str | None = None,
    key_data_pub_key: str | None = None,
) -> dict:
    """Publish a DNSSEC DS record at the registrar. Required: key_tag,
    alg, digest_type, digest. Optional key_data_* fields apply only when
    you're also publishing the DNSKEY-derived form. ``reason`` is
    required and tags the audit row as action=DNSSEC_ADD."""
    try:
        cfg = _get_config()
        return dnssec.create_dnssec_record_impl(
            _get_client(),
            domain,
            key_tag=key_tag,
            alg=alg,
            digest_type=digest_type,
            digest=digest,
            max_sig_life=max_sig_life,
            key_data_flags=key_data_flags,
            key_data_protocol=key_data_protocol,
            key_data_algorithm=key_data_algorithm,
            key_data_pub_key=key_data_pub_key,
            reason=reason,
            audit_enabled=cfg.audit_enabled,
        )
    except PorkbunError as e:
        return _wrap_error(e)


@mcp.tool()
def delete_dnssec_record(domain: str, key_tag: str, reason: str) -> dict:
    """Remove a DNSSEC DS record by key tag. ``reason`` is required;
    audit row action=DNSSEC_DELETE."""
    try:
        cfg = _get_config()
        return dnssec.delete_dnssec_record_impl(
            _get_client(),
            domain,
            key_tag=key_tag,
            reason=reason,
            audit_enabled=cfg.audit_enabled,
        )
    except PorkbunError as e:
        return _wrap_error(e)


@mcp.tool()
def get_ssl_bundle(domain: str) -> dict:
    """Retrieve Porkbun's free DV SSL certificate bundle for ``domain``.
    Returns certificate chain, public key, and private key as PEM strings.
    The cert is auto-issued by Porkbun for zones using their nameservers."""
    try:
        return ssl.get_ssl_bundle_impl(_get_client(), domain)
    except PorkbunError as e:
        return _wrap_error(e)


def main() -> None:
    """Entry point used by the `porkbun-mcp` console script."""
    mcp.run()


if __name__ == "__main__":
    main()
