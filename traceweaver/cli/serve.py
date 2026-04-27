"""
`traceweaver serve` — expose a profile's tool surface to external
agents over the Model Context Protocol.

MVP scope (ROADMAP §4 M4'): stdio transport only. The capture is bound
at server start (scheme A) so the MCP `tools/list` reflects what is
available for that single capture.

Usage::

    traceweaver serve --profile open5gs_5gc --pcap path/to.pcapng

Plug into Claude Desktop's `mcp_config.json` like::

    {
      "mcpServers": {
        "traceweaver-5gc-cap1": {
          "command": "traceweaver",
          "args": ["serve", "--profile", "open5gs_5gc",
                   "--pcap", "/path/to/cap1.pcapng"]
        }
      }
    }

Multi-capture workflows: run one server per capture (see ROADMAP §3.3).
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from traceweaver.cli.analyze import _build_source_spec, _resolve_profile
from traceweaver.serve import build_mcp_server, build_serve_context, run_stdio


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "serve",
        help="Expose profile tools as an MCP server (stdio transport).",
    )
    p.add_argument(
        "--profile",
        required=True,
        help="Profile name (e.g. open5gs_5gc) or path to a profile dir",
    )
    p.add_argument(
        "--pcap",
        help="Path to pcap/pcapng (for pcap-backed profiles)",
    )
    p.add_argument(
        "--log",
        help="Path to a log file (for log-backed profiles)",
    )
    p.add_argument(
        "--transport",
        choices=["stdio"],
        default="stdio",
        help=(
            "MCP transport. Only stdio is supported in this release; "
            "SSE / HTTP transports are deferred to a later phase."
        ),
    )
    p.add_argument(
        "--server-name",
        default="traceweaver",
        help="Name reported to MCP clients during initialization",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    try:
        profile = _resolve_profile(args.profile)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: profile {args.profile!r}: {exc}", file=sys.stderr)
        return 2

    try:
        source_spec = _build_source_spec(profile, args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        serve_ctx = build_serve_context(profile, source_spec)
    except (FileNotFoundError, RuntimeError, ImportError) as exc:
        print(f"error: profile setup failed: {exc}", file=sys.stderr)
        return 3

    server = build_mcp_server(serve_ctx, server_name=args.server_name)

    # All status / banner output must go to stderr — stdout is the MCP
    # transport channel and any stray byte there will desync the client.
    print(
        f"[traceweaver-serve] profile={profile.name} "
        f"tools={len(serve_ctx.tool_registry.values())} "
        f"transport={args.transport}",
        file=sys.stderr,
        flush=True,
    )

    if args.transport == "stdio":
        asyncio.run(run_stdio(server))
        return 0

    # Should be unreachable thanks to argparse `choices`.
    print(f"error: unsupported transport: {args.transport}", file=sys.stderr)
    return 2


__all__ = ["register", "run"]
