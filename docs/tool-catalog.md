# Tool Catalog

49 tools across 7 modules. All mutation tools require a `reason` parameter
and emit an audit row (configurable via `PORKBUN_MCP_AUDIT_HANDLER`).

## Account & Meta (13 tools)

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `ping` | Authenticated readiness probe — confirms credentials and IP allowlist | — |
| `get_pricing` | Full TLD pricing table (cached, 24h TTL) | `force_refresh` |
| `get_pricing_for_tld` | Pricing for a single TLD (from cache) | `tld`, `force_refresh` |
| `list_supported_tlds` | All registrable TLDs, sorted alphabetically (from cache) | `force_refresh` |
| `get_account_balance` | Current account credit balance | — |
| `check_availability` | Check if a domain is available for registration | `domain` |
| `check_bulk_availability` | Check availability for multiple domains (client-side fan-out) | `domains` |
| `get_api_settings` | API spend controls and current month's spend (cents) | — |
| `get_ip` | Caller's public IP address | — |
| `create_invite` | Create a 48h account registration invite | `email`, `return_url` |
| `get_invite_status` | Check invite status (PENDING / ACCEPTED / EXPIRED) | `token` |
| `request_api_key` | Initiate API key authorization request | `name` |
| `retrieve_api_key` | Poll for API key authorization approval | `request_token` |

## Domain Inventory & Info (4 tools)

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `list_domains` | List all domains in the account (paginated, 1000/page) | `start`, `include_labels` |
| `get_domain` | Detailed domain info — expiry, auto-renew, lock state | `domain` |
| `list_labels` | List all domain labels (Porkbun's tagging system) | — |
| `get_url_forwarding` | List URL-forwarding rules for a domain | `domain` |

## Domain Registration / Renewal / Transfer (5 tools)

All financial operations — `cost` is in pennies (USD cents) and must
match the price from `check_availability`.

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `register_domain` | Register a new domain using account credit | `domain`, `cost`, `reason` |
| `renew_domain` | Renew a domain using account credit | `domain`, `cost`, `reason` |
| `transfer_domain` | Initiate inbound domain transfer (5–7 days) | `domain`, `auth_code`, `cost`, `reason` |
| `get_transfer_status` | Most recent transfer record for a domain | `domain` |
| `list_transfers` | All active inbound transfers | — |

## Registrar Mutations (8 tools)

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `update_auto_renew` | Toggle auto-renewal on/off | `domain`, `auto_renew`, `reason` |
| `create_glue` | Create a glue record (host A/AAAA at registrar) | `domain`, `host`, `ips`, `reason` |
| `update_glue` | Replace IPs on an existing glue record | `domain`, `host`, `ips`, `reason` |
| `delete_glue` | Remove a glue record by hostname | `domain`, `host`, `reason` |
| `add_url_forward` | Add URL redirect (301/302) | `domain`, `subdomain`, `location`, `reason`, `type` |
| `delete_url_forward` | Remove a URL forward by record id | `domain`, `record_id`, `reason` |
| `add_label` | Create and attach a label to a domain | `domain`, `label_name`, `color`, `reason` |
| `remove_label` | Detach a label from a domain | `domain`, `label_id`, `reason` |

## DNS Records (9 tools)

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `list_dns_records` | List all DNS records for a domain | `domain` |
| `get_dns_record` | Fetch a single record by id | `domain`, `record_id` |
| `get_dns_records_by_name_type` | Filter records by type + subdomain | `domain`, `type`, `subdomain` |
| `create_dns_record` | Create a DNS record | `domain`, `type`, `name`, `content`, `reason`, `ttl`, `prio` |
| `edit_dns_record` | Edit (full replace) a record by id | `domain`, `record_id`, `type`, `name`, `content`, `reason` |
| `edit_dns_records_by_name_type` | Bulk-edit all records matching type + subdomain | `domain`, `type`, `subdomain`, `content`, `reason` |
| `delete_dns_record` | Delete a record by id | `domain`, `record_id`, `reason` |
| `delete_dns_records_by_name_type` | Bulk-delete all records matching type + subdomain | `domain`, `type`, `subdomain`, `reason` |
| `bulk_create_dns_records` | Create multiple records (client-side fan-out) | `domain`, `records`, `reason` |

## DNSSEC (3 tools)

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `get_dnssec_records` | List DS records published for a domain | `domain` |
| `create_dnssec_record` | Publish a DS record at the registrar | `domain`, `key_tag`, `alg`, `digest_type`, `digest`, `reason` |
| `delete_dnssec_record` | Remove a DS record by key tag | `domain`, `key_tag`, `reason` |

## SSL (1 tool)

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `get_ssl_bundle` | Retrieve Porkbun's free DV SSL certificate (PEM) | `domain` |

## Nameservers (2 tools)

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `get_name_servers` | Get active nameservers for a domain | `domain` |
| `update_name_servers` | Replace a domain's nameservers | `domain`, `ns`, `reason` |

## Marketplace (1 tool)

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `get_marketplace` | Browse domains for sale on the Porkbun marketplace | `start`, `limit`, `query`, `tlds`, `sort_name` |

## Email Hosting (1 tool)

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `set_email_password` | Set password for an email hosting account | `email_address`, `password` |
