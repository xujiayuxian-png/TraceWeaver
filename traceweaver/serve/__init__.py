"""
TraceWeaver `serve` package — expose profile tools to external agents.

Currently only a low-level MCP (Model Context Protocol) adapter is
shipped (`traceweaver.serve.mcp`). HTTP / SSE transports are reserved
for a later release and intentionally absent here so the install
surface stays minimal (only the `mcp-server` extra is required).

The runtime helper (`build_serve_context`) is independent of the
transport so future HTTP / SSE adapters can reuse it verbatim.
"""

from __future__ import annotations

from traceweaver.serve.runtime import (
    ServeContext,
    build_serve_context,
    MultiServeContext,
    build_multi_serve_context,
)
from traceweaver.serve.mcp import build_mcp_server, build_mcp_server_multi, run_stdio

__all__ = [
    "ServeContext",
    "build_serve_context",
    "MultiServeContext",
    "build_multi_serve_context",
    "build_mcp_server",
    "build_mcp_server_multi",
    "run_stdio",
]
