# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- **Network errors surface as `PorkbunAPIError`.** httpx exceptions
  (`ConnectError`, `ReadTimeout`, …) from the underlying transport are now
  wrapped in `PorkbunAPIError(status_code=0)` instead of propagating raw
  to the MCP framework (#47983).
- **Transient 5xx retries for reads.** `PorkbunClient.post()` gained a
  keyword-only `idempotent` flag; read-style endpoints (retrieve/get/list/
  check/ping — 22 call sites) now retry 502/503/504 with exponential
  backoff. Mutations are never retried on 5xx to avoid double-applying
  behind a failing gateway (#47984).
- **`PorkbunRateLimit.retry_after_seconds`** now carries the last known
  `Retry-After` value after retry exhaustion instead of `0.0` (#47985).
- **Audit failures are logged.** JSONL write errors, external emit-binary
  launch failures, and non-zero emit-binary exits now `log.warning` on the
  `porkbun_mcp.audit` logger instead of being silently swallowed; mutations
  still never block on audit problems (#47987, #47988).

### Security
- **Audit payloads no longer visible in the process table.** The external
  audit handler is invoked with `--payload -` and the JSON piped via
  stdin, so payloads (e.g. TXT verification secrets) never appear in
  `/proc/PID/cmdline`. The handler binary must support the `-` stdin
  convention (`inkwell-emit` does as of its 2026-07-05 update) (#47986).

## [0.5.0] — 2026-06-10

### Added
- **TTL disk cache for pricing tools.** `get_pricing`, `get_pricing_for_tld`,
  and `list_supported_tlds` now read through a disk cache at
  `$XDG_CACHE_HOME/porkbun-mcp/pricing.json` (default
  `~/.cache/porkbun-mcp/pricing.json`). 24h TTL, configurable via
  `PORKBUN_PRICING_CACHE_TTL` (seconds, `0` disables). All three tools
  gain a `force_refresh` parameter. Corrupt/unwritable cache falls back
  to live fetch; writes are atomic (`os.replace`). 23 new tests.
- **Pluggable audit handler.** Audit output is now configurable via
  `PORKBUN_MCP_AUDIT_HANDLER` env var: `"jsonl"` (default, writes to
  `~/.local/share/porkbun-mcp/audit.jsonl`), an absolute path to an
  external binary, or `"none"` to disable.

### Security
- Bump `mcp` SDK pin to `>=1.23.0,<1.24.0` to clear three high-severity
  advisories on the prior `<1.9.0` pin.

## [0.4.0] — 2026-05-11

### Added
- **Domain registration, renewal, and transfer tools.** `register_domain`,
  `renew_domain`, `transfer_domain`, `get_transfer_status`, `list_transfers`.
- **Email hosting tools.** `set_email_password`, `request_api_key`,
  `retrieve_api_key`.
- **Marketplace tools.** `get_marketplace`, `add_label`, `remove_label`,
  `list_labels`, `create_invite`, `get_invite_status`.

## [0.3.0] — 2026-05-08

### Added
- **URL forwarding tools.** `add_url_forward`, `get_url_forwarding`,
  `delete_url_forward`.
- **Glue record tools.** `create_glue`, `get_glue`, `update_glue`,
  `delete_glue`.
- **Nameserver tools.** `get_name_servers`, `update_name_servers`,
  `update_auto_renew`.

## [0.2.0] — 2026-05-06

### Added
- **DNS mutation tools.** `create_dns_record`, `edit_dns_record`,
  `delete_dns_record`, `bulk_create_dns_records`,
  `edit_dns_records_by_name_type`, `delete_dns_records_by_name_type`.
- **DNSSEC tools.** `create_dnssec_record`, `delete_dnssec_record`.
- **Domain management.** `get_domain`, `get_api_settings`.
- Audit emit for all mutation tools with `reason` parameter.

## [0.1.0] — 2026-05-04

### Added
- Initial release: 16 read-only tools across 6 modules.
- `account.py`: `ping`, `get_pricing`, `get_account_balance`,
  `check_availability`, `check_bulk_availability`, `get_pricing_for_tld`,
  `list_supported_tlds`.
- `domains.py`: `list_domains`, `get_url_forwarding`, `list_labels`.
- `dns.py`: `list_dns_records`, `get_dns_record`, `get_dns_records_by_name_type`.
- `dnssec.py`: `get_dnssec_records`.
- `ssl.py`: `get_ssl_bundle`.
- `nameservers.py`: `get_name_servers`.
- FastMCP stdio server with env-var configuration.
- 37 unit tests.
