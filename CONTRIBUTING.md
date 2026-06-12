# Contributing to porkbun-mcp-server

Thanks for considering a contribution. Bug reports, docs fixes, and small
improvements are all welcome.

## Dev setup

```bash
git clone https://github.com/Avicennasis/porkbun-mcp-server.git
cd porkbun-mcp-server
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[test]'
pre-commit install
```

## Running the tests

```bash
pytest
```

CI runs the tests against Python 3.11, 3.12, 3.13 — make sure they pass locally
before opening a PR.

## Code style

This project uses [ruff](https://github.com/astral-sh/ruff) for linting and
formatting, wired in via pre-commit. `pre-commit run --all-files` runs the
full check locally. CI runs the same hooks.

## PR checklist

- [ ] Tests added or updated; `pytest` is green locally.
- [ ] `pre-commit run --all-files` is clean.
- [ ] README and docs updated if public behavior changed.
- [ ] `CHANGELOG.md` updated under `[Unreleased]`.

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md).
Be respectful; assume good faith.
