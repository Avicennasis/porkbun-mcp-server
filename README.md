# porkbun-mcp-server

[![CI](https://github.com/Avicennasis/porkbun-mcp-server/actions/workflows/test.yml/badge.svg)](https://github.com/Avicennasis/porkbun-mcp-server/actions/workflows/test.yml)
[![codecov](https://codecov.io/gh/Avicennasis/porkbun-mcp-server/branch/main/graph/badge.svg)](https://codecov.io/gh/Avicennasis/porkbun-mcp-server)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/Avicennasis/porkbun-mcp-server/badge)](https://scorecard.dev/viewer/?uri=github.com/Avicennasis/porkbun-mcp-server)
[![PyPI](https://img.shields.io/pypi/v/porkbun-mcp-server)](https://pypi.org/project/porkbun-mcp-server/)
[![Release](https://img.shields.io/github/v/release/Avicennasis/porkbun-mcp-server?display_name=tag)](https://github.com/Avicennasis/porkbun-mcp-server/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

Model Context Protocol server for [Porkbun's API v3](https://porkbun.com/api/json/v3/documentation) — full coverage of domains, DNS records, DNSSEC, SSL bundle retrieval, glue records, URL forwarding, labels, domain registration/renewal/transfers, marketplace, account management, email hosting, and API key management.

Every mutation tool requires a `reason` argument and emits an audit row via a [pluggable handler](#audit-handler), so DNS changes are always traceable.

## Install

```bash
pip install porkbun-mcp-server
```

Or from source:

```bash
git clone https://github.com/Avicennasis/porkbun-mcp-server.git
cd porkbun-mcp-server
pip install -e ".[dev]"
```

## Register with Claude Code

```bash
claude mcp add porkbun -- porkbun-mcp
```

Or for other MCP clients, add to your configuration:

```json
{
  "mcpServers": {
    "porkbun": {
      "command": "porkbun-mcp",
      "env": {
        "PORKBUN_API_KEY": "pk1_...",
        "PORKBUN_SECRET_KEY": "sk1_..."
      }
    }
  }
}
```

## Configure

| Variable | Required | Description |
|----------|----------|-------------|
| `PORKBUN_API_KEY` | Yes | Your Porkbun API key (`pk1_...`) |
| `PORKBUN_SECRET_KEY` | Yes | Your Porkbun secret key (`sk1_...`) |
| `PORKBUN_MCP_AUDIT_ENABLED` | No | Set `false` to disable audit logging |
| `PORKBUN_MCP_AUDIT_HANDLER` | No | Audit handler — see [Audit Handler](#audit-handler) |
| `PORKBUN_PRICING_CACHE_TTL` | No | Pricing cache TTL in seconds (default: 86400, `0` = no cache) |

Get your API keys at [porkbun.com/account/api](https://porkbun.com/account/api). Ensure API access is enabled for the domains you want to manage.

## Tools (49)

### DNS Records
`list_dns_records` `create_dns_record` `bulk_create_dns_records` `get_dns_record` `get_dns_records_by_name_type` `edit_dns_record` `edit_dns_records_by_name_type` `delete_dns_record` `delete_dns_records_by_name_type`

### DNSSEC
`get_dnssec_records` `create_dnssec_record` `delete_dnssec_record`

### Domains
`list_domains` `get_domain` `check_availability` `check_bulk_availability` `register_domain` `renew_domain` `transfer_domain` `get_transfer_status` `list_transfers` `update_auto_renew` `list_labels` `add_label` `remove_label` `create_glue` `update_glue` `get_glue` `delete_glue` `create_invite` `get_invite_status`

### Nameservers
`get_name_servers` `update_name_servers`

### SSL
`get_ssl_bundle`

### URL Forwarding
`get_url_forwarding` `add_url_forward` `delete_url_forward`

### Account & Pricing
`ping` `get_ip` `get_account_balance` `get_api_settings` `get_pricing` `get_pricing_for_tld` `list_supported_tlds` `request_api_key` `retrieve_api_key`

### Email & Marketplace
`set_email_password` `get_marketplace`

## Audit Handler

Every mutation tool emits an audit row. The handler is configured via `PORKBUN_MCP_AUDIT_HANDLER`:

| Value | Behavior |
|-------|----------|
| *unset* or `jsonl` | Append JSONL to `~/.local/share/porkbun-mcp/audit.jsonl` (default) |
| Absolute path | Shell out to the binary with `--source`, `--category`, `--action`, `--service`, `--reason`, `--target`, `--payload` flags |
| `none` | Disable audit (not recommended) |

Audit failures are always swallowed — mutations are never blocked by logging issues.

### JSONL format

```json
{"ts": "2026-06-12T18:00:00+00:00", "source": "porkbun-mcp", "category": "dns", "action": "POST", "service": "example.com", "target": "A `www`", "reason": "point www to new server"}
```

## Pricing Cache

`get_pricing`, `get_pricing_for_tld`, and `list_supported_tlds` are served from a disk cache at `$XDG_CACHE_HOME/porkbun-mcp/pricing.json` (default `~/.cache/porkbun-mcp/pricing.json`). TTL defaults to 24 hours; override with `PORKBUN_PRICING_CACHE_TTL`. Pass `force_refresh=true` to bypass the cache. Mutable data (DNS records, domain inventory) is never cached.

## Development

```bash
git clone https://github.com/Avicennasis/porkbun-mcp-server.git
cd porkbun-mcp-server
pip install -e ".[dev]"
pytest -v
```

## License

MIT — see [LICENSE](LICENSE).
