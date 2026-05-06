"""
Tests for multi-profile MCP support.

Verifies that:
  - MultiServeContext merges tools with correct prefixes
  - Built-in tools are registered once (unprefixed)
  - profile_for_tool routes correctly
  - build_mcp_server_multi exposes prefixed tools via list_tools
  - call_tool routes to the correct profile's context
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from mcp import types as mcp_types

from traceweaver.core.protocols import (
    SourceHandle,
    Tool,
    ToolContext,
    ToolResult,
    ToolSpec,
)
from traceweaver.core.tools.registry import ToolRegistry
from traceweaver.serve.mcp import build_mcp_server_multi
from traceweaver.serve.runtime import (
    MultiServeContext,
    ServeContext,
    build_multi_serve_context,
)
from traceweaver.serve.session import CaptureSession


# ---- fakes ------------------------------------------------------------

class _FakeHandle(SourceHandle):
    def __init__(self, label: str = "fake") -> None:
        self._label = label

    def iter_records(self, **kwargs: Any) -> Any:
        return iter(())

    def get_records_around(self, *a: Any, **kw: Any) -> Any:
        return []

    def metadata(self) -> dict[str, Any]:
        return {"kind": "fake", "uri": f"memory://{self._label}"}


class _ProfileTool(Tool):
    """A profile-specific tool that returns its profile context."""

    def __init__(self, name: str, profile_label: str) -> None:
        self._label = profile_label
        self.spec = ToolSpec(
            name=name,
            description=f"Tool {name} for {profile_label}.",
            parameters_schema={"type": "object", "properties": {}},
        )

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        return ToolResult(data={"profile": self._label})


def _make_serve_ctx(label: str, tool_names: list[str]) -> ServeContext:
    reg = ToolRegistry()
    for tn in tool_names:
        reg.register(_ProfileTool(tn, label))
    profile = type("P", (), {"name": label})()
    session = CaptureSession()
    session.load(_FakeHandle(label), f"memory://{label}")
    return ServeContext(
        profile=profile,  # type: ignore[arg-type]
        session=session,
        knowledge=None,
        tool_registry=reg,
    )


def _make_multi_ctx() -> MultiServeContext:
    ctx_a = _make_serve_ctx("alpha", ["summarize", "get_detail"])
    ctx_b = _make_serve_ctx("beta", ["summarize", "list_items"])
    return MultiServeContext(
        contexts={"alpha": ctx_a, "beta": ctx_b},
        default_profile="alpha",
    )


# ---- MultiServeContext ------------------------------------------------

class TestMultiServeContext:
    def test_prefixed_tools_in_merged_registry(self) -> None:
        mc = _make_multi_ctx()
        names = sorted(mc.tool_registry.names())
        assert "alpha__summarize" in names
        assert "alpha__get_detail" in names
        assert "beta__summarize" in names
        assert "beta__list_items" in names

    def test_builtin_tools_registered(self) -> None:
        mc = _make_multi_ctx()
        names = mc.tool_registry.names()
        assert "query_records" in names
        assert "search_knowledge" in names
        assert "get_records_around" in names

    def test_list_profiles_registered(self) -> None:
        mc = _make_multi_ctx()
        assert "list_profiles" in mc.tool_registry.names()

    def test_no_unprefixed_profile_tools(self) -> None:
        """Profile-specific tools should NOT appear unprefixed."""
        mc = _make_multi_ctx()
        names = mc.tool_registry.names()
        assert "summarize" not in names
        assert "get_detail" not in names
        assert "list_items" not in names

    def test_profile_for_tool_prefixed(self) -> None:
        mc = _make_multi_ctx()
        name, ctx = mc.profile_for_tool("beta__summarize")
        assert name == "beta"

    def test_profile_for_tool_unprefixed_goes_to_default(self) -> None:
        mc = _make_multi_ctx()
        name, ctx = mc.profile_for_tool("query_records")
        assert name == "alpha"  # default

    def test_make_tool_context_default(self) -> None:
        mc = _make_multi_ctx()
        ctx = mc.make_tool_context()
        assert ctx.profile_name == "alpha"

    def test_make_tool_context_explicit(self) -> None:
        mc = _make_multi_ctx()
        ctx = mc.make_tool_context("beta")
        assert ctx.profile_name == "beta"

    def test_empty_pairs_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            build_multi_serve_context([])

    def test_invalid_default_raises(self) -> None:
        profile = type("P", (), {"name": "alpha"})()
        with pytest.raises(ValueError, match="default_profile"):
            build_multi_serve_context(
                [(profile, type("S", (), {})())],
                default_profile="nonexistent",
            )


# ---- MCP list_tools --------------------------------------------------

class TestMCPMultiListTools:
    def test_list_tools_returns_prefixed_names(self) -> None:
        mc = _make_multi_ctx()
        server = build_mcp_server_multi(mc)
        handler = server.request_handlers[mcp_types.ListToolsRequest]
        req = mcp_types.ListToolsRequest(method="tools/list")
        result = asyncio.run(handler(req))

        names = sorted(t.name for t in result.root.tools)
        assert "alpha__summarize" in names
        assert "beta__summarize" in names
        assert "list_profiles" in names

    def test_list_tools_no_duplicate_builtins(self) -> None:
        mc = _make_multi_ctx()
        server = build_mcp_server_multi(mc)
        handler = server.request_handlers[mcp_types.ListToolsRequest]
        req = mcp_types.ListToolsRequest(method="tools/list")
        result = asyncio.run(handler(req))

        names = [t.name for t in result.root.tools]
        assert names.count("query_records") == 1


# ---- MCP call_tool routing -------------------------------------------

class TestMCPMultiCallTool:
    def _call(self, server, name: str, args: dict | None = None):
        handler = server.request_handlers[mcp_types.CallToolRequest]
        req = mcp_types.CallToolRequest(
            method="tools/call",
            params=mcp_types.CallToolRequestParams(name=name, arguments=args or {}),
        )
        return asyncio.run(handler(req))

    def test_prefixed_tool_routes_to_correct_profile(self) -> None:
        mc = _make_multi_ctx()
        server = build_mcp_server_multi(mc)

        result = self._call(server, "alpha__summarize")
        payload = json.loads(result.root.content[0].text)
        assert payload["data"]["profile"] == "alpha"

        result = self._call(server, "beta__summarize")
        payload = json.loads(result.root.content[0].text)
        assert payload["data"]["profile"] == "beta"

    def test_list_profiles_returns_all_profiles(self) -> None:
        mc = _make_multi_ctx()
        server = build_mcp_server_multi(mc)

        result = self._call(server, "list_profiles")
        payload = json.loads(result.root.content[0].text)
        names = [p["name"] for p in payload["data"]["profiles"]]
        assert sorted(names) == ["alpha", "beta"]
        assert payload["data"]["default"] == "alpha"
