# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 0.x     | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability, please report it responsibly:

1. **Do not** open a public issue.
2. Email **avicennasis@gmail.com** with a description of the vulnerability.
3. Include steps to reproduce if possible.

You should receive a response within 72 hours. If the vulnerability is confirmed, a fix will be released as soon as practical and you will be credited (unless you prefer otherwise).

## Scope

This server handles Porkbun API credentials (`PORKBUN_API_KEY`, `PORKBUN_SECRET_KEY`) and makes authenticated API calls to Porkbun's v3 API. Security-relevant areas include:

- Credential handling and storage
- Audit log integrity
- Input validation for DNS record mutations
- Dependency supply chain
