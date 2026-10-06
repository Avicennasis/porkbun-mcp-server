"""The server module must import and register its tools.

0.6.0 shipped to PyPI unable to start: ``server.py`` imported
``mcp.server.fastmcp`` while ``pyproject.toml`` required ``mcp>=2.3.0`` (mcp 2
removed FastMCP in favour of ``mcp.server.mcpserver.MCPServer``). CI stayed green
because no test imported ``server.py`` -- every other test exercises the
``tools/*_impl`` functions directly. These tests close that gap.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _catalog_tool_names() -> set[str]:
    text = (REPO / "docs" / "tool-catalog.md").read_text(encoding="utf-8")
    return set(re.findall(r"^\| `(\w+)` \|", text, re.MULTILINE))


def test_server_module_imports() -> None:
    from porkbun_mcp import server

    assert callable(server.main)
    assert server.mcp.name == "porkbun"


@pytest.mark.asyncio
async def test_registered_tools_match_the_catalog() -> None:
    from porkbun_mcp import server

    tools = await server.mcp.list_tools()
    names = {t.name for t in tools}
    assert len(names) == len(tools), "duplicate tool names"
    assert names == _catalog_tool_names()


@pytest.mark.asyncio
async def test_every_mutation_tool_requires_reason() -> None:
    """The audit contract: a tool that changes state cannot be called without ``reason``."""
    from porkbun_mcp import server

    tools = await server.mcp.list_tools()
    with_reason = {t.name for t in tools if "reason" in t.input_schema.get("properties", {})}
    for name in with_reason:
        tool = next(t for t in tools if t.name == name)
        assert "reason" in tool.input_schema.get("required", []), name


def test_version_matches_pyproject() -> None:
    from porkbun_mcp import __version__

    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert __version__ == project["version"]


def test_documented_tool_counts_match_the_catalog() -> None:
    count = len(_catalog_tool_names())
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    catalog = (REPO / "docs" / "tool-catalog.md").read_text(encoding="utf-8")
    assert f"## Tools ({count})" in readme
    assert catalog.splitlines()[2].startswith(f"{count} tools across")
