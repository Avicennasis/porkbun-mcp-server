# Contributing

Contributions are welcome! Here's how to get started.

## Development Setup

```bash
git clone https://github.com/Avicennasis/porkbun-mcp-server.git
cd porkbun-mcp-server
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Running Tests

```bash
pytest -v
```

Tests use [vcrpy](https://github.com/kevin1024/vcrpy) cassettes for API responses — no live Porkbun account needed for the test suite.

## Code Style

This project uses [Ruff](https://docs.astral.sh/ruff/) for linting and formatting:

```bash
ruff check src/ tests/
ruff format src/ tests/
```

## Pull Requests

1. Fork the repo and create a feature branch.
2. Add tests for new functionality.
3. Ensure `pytest` and `ruff check` pass.
4. Open a PR against `main`.

## Adding a New Tool

1. Add the implementation in the appropriate `src/porkbun_mcp/tools/<module>.py`.
2. If the tool is a mutation, call `audit.emit_dns_change()` or `audit.emit_domain_change()` with a `reason` parameter.
3. Add tests in `tests/test_tools_<module>.py`.
4. Update the tool count in `README.md`.
