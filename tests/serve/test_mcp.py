"""
Tests for `traceweaver.serve.mcp` — verify the MCP adapter renders
`ToolRegistry` correctly and dispatches `call_tool` through the same
registry contract the kernel uses.

We deliberately do *not* spin up the stdio transport here (that is an
integration-level concern). Instead we drive the server's internal
request handlers directly, which is the same surface the SDK invokes
once a real client speaks to it.
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
from traceweaver.serve.mcp import build_mcp_server
from traceweaver.serve.runtime import ServeContext
from traceweaver.serve.session import CaptureSession


# ---- minimal fakes ---------------------------------------------------


class _FakeHandle(SourceHandle):
    """Stand-in for a real source handle; tools below ignore it."""

    def iter_records(self, scope: Any = None) -> Any:  # pragma: no cover - unused
        return iter(())

    def get_records_around(
        self, anchor: Any, *, before: int = 0, after: int = 0
    ) -> Any:  # pragma: no cover - unused
        return []

    def metadata(self) -> dict[str, Any]:
        return {"kind": "fake", "uri": "memory://fake"}


class _EchoTool(Tool):
    """Tool that echoes its arguments back as `data`."""

    spec = ToolSpec(
        name="echo",
        description="Return the argument verbatim.",
        parameters_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
    )

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        return ToolResult(data={"echo": kwargs["value"]}, refs=["frame:1"])


class _BoomTool(Tool):
    """Tool that always raises (covers the error path)."""

    spec = ToolSpec(
        name="boom",
        description="Always raises ValueError.",
        parameters_schema={"type": "object", "properties": {}},
    )

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        raise ValueError("intentional failure")


def _make_serve_ctx() -> ServeContext:
    """Build a `ServeContext` that bypasses the profile/source pipeline."""
    reg = ToolRegistry()
    reg.register(_EchoTool())
    reg.register(_BoomTool())
    profile = type("FakeProfile", (), {"name": "fake_profile"})()
    session = CaptureSession()
    session.load(_FakeHandle(), "memory://fake")
    return ServeContext(
        profile=profile,  # type: ignore[arg-type]
        session=session,
        knowledge=None,
        tool_registry=reg,
    )


# ---- to_mcp_tool() ---------------------------------------------------


def test_to_mcp_tool_emits_required_fields() -> None:
    spec = ToolSpec(
        name="x",
        description="d",
        parameters_schema={"type": "object", "properties": {"a": {"type": "string"}}},
    )
    rendered = spec.to_mcp_tool()
    assert rendered == {
        "name": "x",
        "description": "d",
        "inputSchema": {"type": "object", "properties": {"a": {"type": "string"}}},
    }


def test_to_mcp_tool_defaults_empty_schema() -> None:
    spec = ToolSpec(name="x", description="d")
    rendered = spec.to_mcp_tool()
    assert rendered["inputSchema"] == {"type": "object", "properties": {}}


# ---- list_tools handler ----------------------------------------------


def _list_tools_handler(server) -> Any:
    return server.request_handlers[mcp_types.ListToolsRequest]


def _call_tool_handler(server) -> Any:
    return server.request_handlers[mcp_types.CallToolRequest]


def test_list_tools_returns_every_registry_entry() -> None:
    serve_ctx = _make_serve_ctx()
    server = build_mcp_server(serve_ctx)

    handler = _list_tools_handler(server)
    req = mcp_types.ListToolsRequest(method="tools/list")
    result = asyncio.run(handler(req))

    # `ServerResult` wraps a `ListToolsResult`.
    assert isinstance(result.root, mcp_types.ListToolsResult)
    names = sorted(t.name for t in result.root.tools)
    assert names == ["boom", "echo"]


def test_list_tools_preserves_input_schema() -> None:
    serve_ctx = _make_serve_ctx()
    server = build_mcp_server(serve_ctx)

    handler = _list_tools_handler(server)
    req = mcp_types.ListToolsRequest(method="tools/list")
    result = asyncio.run(handler(req))

    by_name = {t.name: t for t in result.root.tools}
    assert by_name["echo"].inputSchema["required"] == ["value"]


# ---- call_tool handler -----------------------------------------------


def _make_call(name: str, arguments: dict[str, Any] | None) -> mcp_types.CallToolRequest:
    return mcp_types.CallToolRequest(
        method="tools/call",
        params=mcp_types.CallToolRequestParams(name=name, arguments=arguments),
    )


def test_call_tool_returns_data_envelope() -> None:
    serve_ctx = _make_serve_ctx()
    server = build_mcp_server(serve_ctx)
    handler = _call_tool_handler(server)

    result = asyncio.run(handler(_make_call("echo", {"value": "hi"})))

    # Response is `ServerResult(CallToolResult(content=[TextContent(...)], ...))`.
    inner = result.root
    assert isinstance(inner, mcp_types.CallToolResult)
    assert inner.isError in (False, None)
    assert len(inner.content) == 1
    text_block = inner.content[0]
    assert text_block.type == "text"

    payload = json.loads(text_block.text)
    assert payload["data"] == {"echo": "hi"}
    assert payload["refs"] == ["frame:1"]
    assert "truncated" not in payload  # default False


def test_call_tool_rejects_missing_required_argument() -> None:
    """
    MCP SDK runs its own JSON-schema validation against `inputSchema`
    before our handler executes (the SDK's `validate_input=True`
    default). The exact phrasing therefore comes from the SDK's
    jsonschema layer rather than `ToolRegistry`; either is acceptable
    — what matters is that `isError=True` and the failure mentions
    the missing parameter.
    """
    serve_ctx = _make_serve_ctx()
    server = build_mcp_server(serve_ctx)
    handler = _call_tool_handler(server)

    result = asyncio.run(handler(_make_call("echo", {})))
    inner = result.root
    assert isinstance(inner, mcp_types.CallToolResult)
    assert inner.isError is True
    text = inner.content[0].text
    assert "value" in text.lower(), text
    assert ("required" in text.lower()) or ("missing" in text.lower()), text


def test_call_tool_unknown_tool_is_isError() -> None:
    serve_ctx = _make_serve_ctx()
    server = build_mcp_server(serve_ctx)
    handler = _call_tool_handler(server)

    result = asyncio.run(handler(_make_call("nope", {})))
    inner = result.root
    assert isinstance(inner, mcp_types.CallToolResult)
    assert inner.isError is True
    payload = json.loads(inner.content[0].text)
    assert "unknown tool" in payload["error"]


def test_call_tool_value_error_in_tool_propagates_as_isError() -> None:
    serve_ctx = _make_serve_ctx()
    server = build_mcp_server(serve_ctx)
    handler = _call_tool_handler(server)

    result = asyncio.run(handler(_make_call("boom", {})))
    inner = result.root
    assert isinstance(inner, mcp_types.CallToolResult)
    assert inner.isError is True
    payload = json.loads(inner.content[0].text)
    assert "intentional failure" in payload["error"]
