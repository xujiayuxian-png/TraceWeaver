"""
Smoke a real `traceweaver serve --transport stdio` instance.

Starts the CLI in a subprocess, connects via the MCP SDK's stdio
client, walks through `initialize → list_tools → call_tool`, and
prints what an external agent (Claude Desktop, Cursor, etc.) would
see. No pytest involvement; this is for hands-on verification.

Usage::

    .venv\\Scripts\\python scripts/smoke_mcp_serve.py \\
        --profile open5gs_5gc \\
        --pcap tests/fixtures/pcap/01_registration_success.pcapng

Exits 0 on success, 1 on failure. Prints a short summary either way.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def smoke(profile: str, pcap: Path) -> int:
    # We launch the CLI through the same Python interpreter so the
    # subprocess sees the in-tree TraceWeaver. Using `-m traceweaver`
    # would fail because `traceweaver` is a package without
    # `__main__.py`; route through the entry function instead.
    server_params = StdioServerParameters(
        command=sys.executable,
        args=[
            "-c",
            "from traceweaver.cli import main; "
            f"raise SystemExit(main(['serve', '--profile', '{profile}', "
            f"'--pcap', r'{pcap}']))",
        ],
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            init_result = await session.initialize()
            print(
                f"[smoke] initialized: server={init_result.serverInfo.name} "
                f"protocol={init_result.protocolVersion}"
            )

            tools = await session.list_tools()
            tool_names = sorted(t.name for t in tools.tools)
            print(f"[smoke] tools/list returned {len(tool_names)} tools:")
            for n in tool_names:
                print(f"          - {n}")

            print("[smoke] calling summarize_capture ...")
            res = await session.call_tool("summarize_capture", {})
            if res.isError:
                print("[smoke] FAILED: summarize_capture returned an error", file=sys.stderr)
                for c in res.content:
                    if hasattr(c, "text"):
                        print(c.text, file=sys.stderr)
                return 1

            block = res.content[0]
            if not hasattr(block, "text"):
                print("[smoke] FAILED: unexpected content block type", file=sys.stderr)
                return 1
            payload = json.loads(block.text)
            data = payload.get("data") or {}
            event_count = sum(
                (entry.get("count") or 0)
                for entry in (data.get("event_inventory") or [])
            )
            ue_count = len(data.get("ue_overview") or [])
            print(
                f"[smoke] summarize_capture -> {ue_count} UE(s), "
                f"{event_count} total events across event_inventory"
            )

    print("[smoke] OK")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="open5gs_5gc")
    ap.add_argument(
        "--pcap",
        type=Path,
        default=Path("tests/fixtures/pcap/01_registration_success.pcapng"),
    )
    args = ap.parse_args()

    if not args.pcap.is_file():
        print(f"[smoke] pcap not found: {args.pcap}", file=sys.stderr)
        return 2

    return asyncio.run(smoke(args.profile, args.pcap.resolve()))


if __name__ == "__main__":
    raise SystemExit(main())
