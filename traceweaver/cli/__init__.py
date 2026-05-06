"""
TraceWeaver CLI (platform-v2 §4 Layer 5).

`traceweaver <command>` entry point. M3 ships a single command:

    traceweaver analyze --profile <name> --pcap <path> "<question>"

Which is enough to drive the 5GC profile against a real capture. Other
commands (e.g. `describe-profile`, `list-profiles`) will land with later
M-phases.
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    # PowerShell's default GBK codec chokes on any non-latin punctuation
    # we print; force stdout/stderr to UTF-8 on Windows so the CLI never
    # dies mid-report.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass

    parser = argparse.ArgumentParser(
        prog="traceweaver",
        description="TraceWeaver: LLM-first multi-source diagnosis platform",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    from traceweaver.cli.analyze import register as register_analyze
    from traceweaver.cli.profile import register as register_profile
    from traceweaver.cli.replay import register as register_replay
    from traceweaver.cli.serve import register as register_serve
    from traceweaver.cli.validate_profile import register as register_validate

    register_analyze(sub)
    register_profile(sub)
    register_replay(sub)
    register_serve(sub)
    register_validate(sub)

    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


__all__ = ["main"]
