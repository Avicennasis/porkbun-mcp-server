# Changelog

## 0.1.0 (unreleased)

### Phase 6
- 2026-06-10: TTL disk cache for the pricing table (claudecode#3168).
  New `pricing_cache.py`: persists the last successful `/pricing/get`
  payload to `$XDG_CACHE_HOME/porkbun-mcp/pricing.json` (default
  `~/.cache/porkbun-mcp/pricing.json`), 24h TTL configurable via
  `PORKBUN_PRICING_CACHE_TTL` (seconds, `0` disables). `get_pricing`,
  `get_pricing_for_tld`, and `list_supported_tlds` all read through the
  same cache and gain a `force_refresh` parameter. Corrupt/unwritable
  cache falls back to live fetch; writes are atomic (`os.replace`).
  23 new tests (119 total).

### Security
- 2026-05-11: bump `mcp` SDK pin to `>=1.23.0,<1.24.0` (running 1.23.3) to clear three high-severity advisories on the prior `<1.9.0` pin: MCP Python SDK missing DNS rebinding protection (fixed 1.23.0), FastMCP validation-error DoS (1.9.4), Streamable HTTP Transport unhandled-exception DoS (1.10.0). digitalocean-dns-mcp is the fleet canary on `<2.0.0`. All 37 tests pass on 1.23.3.

### Phase 0
- Repo scaffold, MIT license, hatchling build, src/ layout.
- `secrets.py` parses `## Porkbun` section out of `~/.claude/secrets.md`.
- `config.py` Settings dataclass with audit-log paths.
- `client.py` httpx wrapper, POST-only with credential injection, 429 retry/backoff.
- `errors.py` PorkbunError hierarchy + AuditLogPathDenied.
- `server.py` FastMCP entrypoint (no `__future__ annotations` — landmine).
- `tools/account.py` ping_impl.
- 19 unit tests; registered as `porkbun: ✓ Connected` at user scope.

### Phase 1
- 15 read tools across 6 modules:
  - `account.py`: `get_pricing`, `get_account_balance`, `check_availability`, `check_bulk_availability` (client-side fan-out), `get_pricing_for_tld`, `list_supported_tlds`
  - `domains.py`: `list_domains` (with pagination + `include_labels`), `get_url_forwarding`, `list_labels`
  - `nameservers.py`: `get_name_servers`
  - `dns.py`: `list_dns_records`, `get_dns_record`, `get_dns_records_by_name_type`
  - `dnssec.py`: `get_dnssec_records`
  - `ssl.py`: `get_ssl_bundle`
- Tool surface: 16 (all read-only). Mutation tools come in Phases 2-4.
- `fake_client` fixture promoted to `conftest.py` for DRY.
- 37 unit tests; FastMCP `list_tools()` confirms clean registration.
