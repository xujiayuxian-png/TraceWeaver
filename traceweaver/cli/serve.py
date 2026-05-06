"""
`traceweaver serve` — expose profile tools to external agents over MCP.

Minimal startup (capture loaded at runtime by the agent)::

    traceweaver serve --profile open5gs_5gc

With pre-loaded capture::

    traceweaver serve --profile open5gs_5gc --pcap cap.pcapng

Multi-profile::

    traceweaver serve \\
        --profile open5gs_5gc \\
        --profile web_l4l7_failures \\
        --default-profile open5gs_5gc

When multiple profiles are loaded, profile-specific tools are prefixed
with ``<profile>__``.  The agent calls ``load_capture(path=...)`` to
load a pcap at runtime — no server restart needed.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from traceweaver.cli.analyze import _build_source_spec, _resolve_profile
from traceweaver.serve import (
    build_mcp_server,
    build_mcp_server_multi,
    build_multi_serve_context,
    build_serve_context,
    run_stdio,
)


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "serve",
        help="Expose profile tools as an MCP server (stdio transport).",
    )
    p.add_argument(
        "--profile",
        action="append",
        default=[],
        help=(
            "Profile name or path (repeatable for multi-profile). "
            "Each --profile may optionally be followed by a matching --pcap."
        ),
    )
    p.add_argument(
        "--pcap",
        action="append",
        default=[],
        help=(
            "Path to pcap/pcapng (matched to --profile by order). "
            "If omitted for a profile, use load_capture at runtime."
        ),
    )
    p.add_argument(
        "--log",
        action="append",
        default=[],
        help="Path to a log file (matched to --profile by order).",
    )
    p.add_argument(
        "--default-profile",
        default=None,
        help=(
            "Profile whose source/knowledge backs the unprefixed built-in "
            "tools.  Defaults to the first --profile."
        ),
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
    if not args.profile:
        print("error: at least one --profile is required", file=sys.stderr)
        return 2

    # Resolve profiles and build source specs (pcap is optional).
    pairs: list[tuple] = []
    for idx, profile_name in enumerate(args.profile):
        try:
            profile = _resolve_profile(profile_name)
        except (FileNotFoundError, ValueError) as exc:
            print(f"error: profile {profile_name!r}: {exc}", file=sys.stderr)
            return 2

        pcap = args.pcap[idx] if idx < len(args.pcap) else None
        log = args.log[idx] if idx < len(args.log) else None

        source_spec = None
        if pcap or log:
            ns = argparse.Namespace(pcap=pcap, log=log)
            try:
                source_spec = _build_source_spec(profile, ns)
            except ValueError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2

        pairs.append((profile, source_spec))

    if len(pairs) == 1:
        profile, source_spec = pairs[0]
        try:
            serve_ctx = build_serve_context(profile, source_spec)
        except (FileNotFoundError, RuntimeError, ImportError) as exc:
            print(f"error: profile setup failed: {exc}", file=sys.stderr)
            return 3

        server = build_mcp_server(serve_ctx, server_name=args.server_name)
        cap_status = "pre-loaded" if source_spec else "use load_capture"
        print(
            f"[traceweaver-serve] profile={profile.name} "
            f"tools={len(serve_ctx.tool_registry.values())} "
            f"capture={cap_status} transport={args.transport}",
            file=sys.stderr,
            flush=True,
        )
    else:
        try:
            multi_ctx = build_multi_serve_context(
                pairs, default_profile=args.default_profile
            )
        except (FileNotFoundError, RuntimeError, ImportError, ValueError) as exc:
            print(f"error: multi-profile setup failed: {exc}", file=sys.stderr)
            return 3

        server = build_mcp_server_multi(
            multi_ctx, server_name=args.server_name
        )
        tool_count = len(multi_ctx.tool_registry.values())
        names = list(multi_ctx.contexts.keys())
        print(
            f"[traceweaver-serve] profiles={names} "
            f"default={multi_ctx.default_profile} "
            f"tools={tool_count} transport={args.transport}",
            file=sys.stderr,
            flush=True,
        )

    if args.transport == "stdio":
        asyncio.run(run_stdio(server))
        return 0

    print(f"error: unsupported transport: {args.transport}", file=sys.stderr)
    return 2


__all__ = ["register", "run"]
