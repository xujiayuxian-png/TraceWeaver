"""
`traceweaver profile list` — show every profile this Python environment
can discover, broken down by source (entry_point / builtin / local dir).

A few words on intent: this command is the primary "did pip install
work?" verification step for users following
``docs/guides/python-packaging-profiles.md``. It must stay
side-effect-free (no LLM calls, no source ingestion) so even a broken
profile only surfaces as a warning line, not a hard failure.
"""

from __future__ import annotations

import argparse
import json

from traceweaver.core.profile import ProfileLoader


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "profile",
        help="Inspect / manage profiles available in this environment.",
    )
    sub = p.add_subparsers(dest="profile_action", required=True)

    lst = sub.add_parser(
        "list",
        help="List every discoverable profile and its origin.",
    )
    lst.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    lst.set_defaults(func=run_list)


def run_list(args: argparse.Namespace) -> int:
    loader = ProfileLoader()
    discovered = loader.discover_with_source()

    if args.format == "json":
        payload = [
            {
                "name": src.name,
                "origin": src.origin,
                "path": str(src.path),
            }
            for src in sorted(discovered.values(), key=lambda s: s.name)
        ]
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    if not discovered:
        print("(no profiles found)")
        print(
            "Try: pip install <a-traceweaver-profile-package>, drop a profile "
            "directory into ~/.traceweaver/profiles/, or set "
            "TRACEWEAVER_PROFILES_PATH."
        )
        return 0

    name_w = max(len(n) for n in discovered)
    origin_w = max(len(s.origin) for s in discovered.values())
    print(f"{'NAME':<{name_w}}  {'ORIGIN':<{origin_w}}  PATH")
    for src in sorted(discovered.values(), key=lambda s: s.name):
        print(f"{src.name:<{name_w}}  {src.origin:<{origin_w}}  {src.path}")
    return 0


__all__ = ["register", "run_list"]
