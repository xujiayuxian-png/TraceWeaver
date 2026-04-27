"""
MCP (Model Context Protocol) adapter on top of `ServeContext`.

The `mcp` Python SDK exposes a low-level `Server` whose tool surface is
declared via two decorators: `@server.list_tools()` (returns the
catalogue) and `@server.call_tool()` (dispatches a single invocation).
This module wires those two callbacks to the `ToolRegistry` already
populated by `build_serve_context`.

Design constraints honoured here:
  * Tools never embed verdicts; the `ToolRegistry` already enforces the
    forbidden-keys contract (`registry._enforce_result_contract`), so
    the MCP layer can simply forward `result.data` verbatim.
  * Responses are returned as a single `TextContent` carrying a JSON
    document. We use JSON (not the structured `outputSchema` field)
    because every existing tool already returns plain dicts, and the
    JSON envelope is the most interoperable form across MCP clients.
  * Errors raised by the registry (unknown tool, bad arguments, schema
    violation) are converted to a JSON envelope `{"error": "..."}`
    rather than re-raised — the MCP spec lets `call_tool` mark a
    response as `isError=True`, which we set via the SDK's normal
    error path so external agents can react accordingly.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server import Server
from mcp.types import TextContent
from mcp.types import Tool as MCPTool

from traceweaver.serve.runtime import ServeContext


def build_mcp_server(
    serve_ctx: ServeContext,
    *,
    server_name: str = "traceweaver",
) -> Server:
    """
    Build a configured low-level MCP server from a ready-to-use
    `ServeContext`. The returned server is *not* started; the caller
    decides which transport to run it on (`run_stdio` covers the MVP
    case; HTTP / SSE adapters can be added later without touching this
    function).
    """
    server: Server = Server(server_name)

    @server.list_tools()
    async def _list_tools() -> list[MCPTool]:
        return [
            MCPTool(**tool.spec.to_mcp_tool())
            for tool in serve_ctx.tool_registry.values()
        ]

    @server.call_tool()
    async def _call_tool(
        name: str, arguments: dict[str, Any] | None
    ) -> list[TextContent]:
        ctx = serve_ctx.make_tool_context()
        try:
            result = serve_ctx.tool_registry.invoke(name, arguments or {}, ctx)
        except (KeyError, ValueError, TypeError) as exc:
            # Surface the failure as a structured payload. The SDK will
            # also propagate the exception to the client as `isError`.
            err_payload = {"error": f"{type(exc).__name__}: {exc}"}
            raise _ToolInvocationError(json.dumps(err_payload, ensure_ascii=False)) from exc

        payload: dict[str, Any] = {"data": result.data}
        if result.refs:
            payload["refs"] = list(result.refs)
        if result.truncated:
            payload["truncated"] = True
        return [
            TextContent(
                type="text",
                text=json.dumps(payload, ensure_ascii=False, default=str),
            )
        ]

    return server


class _ToolInvocationError(Exception):
    """
    Internal exception used to translate registry errors into
    structured MCP error responses. The raised message is already a
    JSON string so the SDK can ship it to the client unchanged.
    """


async def run_stdio(server: Server) -> None:
    """
    Drive `server` over the MCP stdio transport — i.e. the form most
    desktop clients (Claude Desktop, Cursor, Cline) expect.

    Kept as a thin wrapper so test code can stub it out without
    importing `mcp.server.stdio` themselves.
    """
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


__all__ = ["build_mcp_server", "run_stdio"]
