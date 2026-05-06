"""
End-to-end MCP smoke: spin up a real (in-memory) MCP server backed by
`build_mcp_server` and drive it with the SDK's `ClientSession`. This
proves the full handshake works (initialize → list_tools → call_tool)
without going through stdio / a separate process.

If this passes alongside the unit tests in `test_mcp.py` we have a
high-confidence signal that `traceweaver serve --transport stdio` will
also work end-to-end (only the transport layer differs).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

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


class _FakeHandle(SourceHandle):
    def iter_records(self, scope: Any = None) -> Any:
        return iter(())

    def get_records_around(self, anchor: Any, *, before: int = 0, after: int = 0) -> Any:
        return []

    def metadata(self) -> dict[str, Any]:
        return {"kind": "fake"}


class _PingTool(Tool):
    spec = ToolSpec(
        name="ping",
        description="Return a fixed JSON envelope so the test can assert it.",
        parameters_schema={"type": "object", "properties": {}},
    )

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        return ToolResult(data={"pong": True, "profile": ctx.profile_name}, refs=["frame:42"])


def _make_server():
    reg = ToolRegistry()
    reg.register(_PingTool())
    profile = type("FakeProfile", (), {"name": "fake_profile"})()
    session = CaptureSession()
    session.load(_FakeHandle(), "memory://fake")
    serve_ctx = ServeContext(
        profile=profile,  # type: ignore[arg-type]
        session=session,
        knowledge=None,
        tool_registry=reg,
    )
    return build_mcp_server(serve_ctx, server_name="traceweaver-test")


def test_e2e_initialize_list_call() -> None:
    async def scenario() -> dict[str, Any]:
        server = _make_server()
        async with create_connected_server_and_client_session(server) as session:
            # `create_connected_server_and_client_session` already
            # performs the initialize handshake; jump straight into
            # tool inspection.
            tools = await session.list_tools()
            tool_names = sorted(t.name for t in tools.tools)

            call_result = await session.call_tool("ping", {})
            assert call_result.isError in (False, None)
            text = call_result.content[0].text
            payload = json.loads(text)

            return {"tool_names": tool_names, "payload": payload}

    out = asyncio.run(scenario())
    assert out["tool_names"] == ["ping"]
    assert out["payload"]["data"] == {"pong": True, "profile": "fake_profile"}
    assert out["payload"]["refs"] == ["frame:42"]
