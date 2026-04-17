"""
`traceweaver analyze` — run one diagnosis against a single pcap (for now).

Responsibilities:
  1. Resolve a profile by name (built-in first, then `ProfileLoader` for
     locally-installed profiles).
  2. Build a `SourceSpec` from `--pcap` plus the profile's `source_config`.
  3. Ingest the source, wrapping it with the profile's enrichers.
  4. Build a `KnowledgeStore` from the profile's knowledge items.
  5. Register the profile's tools (plus the always-available built-ins).
  6. Drive `AgentKernel.run_with_profile` with the user question.
  7. Print the result (JSON by `--format json`, else human summary).

Errors are reported as non-zero exit codes with a single-line message on
stderr; the full trace goes to stderr only when `--verbose` is set.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Any

from traceweaver.cli.diagnose_result import format_result
from traceweaver.core.intelligence import LLMIntelligence
from traceweaver.core.kernel import AgentKernel
from traceweaver.core.profile import Profile, load_profile_from_dir
from traceweaver.core.profile.loader import ProfileLoader
from traceweaver.core.profile.runtime import (
    build_knowledge_store,
    ingest_for_profile,
)
from traceweaver.core.source import SourceSpec
from traceweaver.core.tools.builtin import register_builtin_tools
from traceweaver.core.tools.loader import load_profile_tools
from traceweaver.core.tools.registry import ToolRegistry


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "analyze",
        help="Run a single diagnosis against one capture / log file.",
    )
    p.add_argument("question", help="User request to pass to the agent")
    p.add_argument("--profile", required=True, help="Profile name (e.g. open5gs_5gc)")
    p.add_argument("--pcap", help="Path to pcap/pcapng (for pcap-backed profiles)")
    p.add_argument("--log", help="Path to a log file (for log-backed profiles)")
    p.add_argument(
        "--model",
        default="openai/qwen/qwen3.5-9b",
        help="litellm model id (default: LM Studio Qwen3.5-9b baseline)",
    )
    p.add_argument(
        "--api-base",
        default="http://127.0.0.1:1234/v1",
        help="OpenAI-compatible API base (default: LM Studio)",
    )
    p.add_argument(
        "--format",
        choices=["human", "json"],
        default="human",
        help="Output format (default: human)",
    )
    p.add_argument(
        "--trace",
        action="store_true",
        help="Print the full per-round trace (human format only)",
    )
    p.set_defaults(func=run)


# ---- command entry ----------------------------------------------------

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
        handle = ingest_for_profile(profile, source_spec)
    except (FileNotFoundError, RuntimeError, ImportError) as exc:
        print(f"error: source ingest failed: {exc}", file=sys.stderr)
        return 3

    knowledge = build_knowledge_store(profile)

    registry = ToolRegistry()
    register_builtin_tools(registry)
    try:
        load_profile_tools(registry, profile.tools)
    except (ImportError, AttributeError, TypeError, ValueError) as exc:
        print(f"error: profile tools: {exc}", file=sys.stderr)
        return 4

    intelligence = LLMIntelligence(model=args.model, api_base=args.api_base)
    kernel = AgentKernel(intelligence=intelligence, registry=registry)

    result = kernel.run_with_profile(
        profile,
        args.question,
        source_handle=handle,
        knowledge_store=knowledge,
    )

    if args.format == "json":
        print(
            json.dumps(
                {
                    "stop_reason": result.stop_reason,
                    "rounds_used": result.trace.rounds_used(),
                    "tool_calls_total": result.trace.tool_calls_total(),
                    "final_json": result.final_json,
                    "final_text": result.final_text,
                    "error": result.error,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(format_result(result, show_trace=args.trace))

    return 0 if result.ok else 1


# ---- helpers ----------------------------------------------------------

def _resolve_profile(name_or_path: str) -> Profile:
    """
    Resolve a profile identifier:
      * an absolute/relative filesystem path to a profile dir, OR
      * a name matching a built-in profile (``traceweaver.profiles.<name>``), OR
      * a name discoverable by `ProfileLoader`.
    """
    candidate = Path(name_or_path)
    if candidate.exists() and (candidate / "profile.yaml").is_file():
        return load_profile_from_dir(candidate)

    builtin = _builtin_profile_path(name_or_path)
    if builtin is not None and (builtin / "profile.yaml").is_file():
        return load_profile_from_dir(builtin)

    loader = ProfileLoader()
    try:
        return loader.load(name_or_path)
    except KeyError:
        raise FileNotFoundError(
            "not found as path, built-in, or on TRACEWEAVER_PROFILES_PATH"
        ) from None


def _builtin_profile_path(name: str) -> Path | None:
    """Try to resolve `traceweaver.profiles.<name>` to its package dir."""
    mod_name = f"traceweaver.profiles.{name}"
    try:
        mod = importlib.import_module(mod_name)
    except ImportError:
        return None
    mod_file = getattr(mod, "__file__", None)
    if mod_file is None:
        return None
    return Path(mod_file).resolve().parent


def _build_source_spec(profile: Profile, args: argparse.Namespace) -> SourceSpec:
    """Pick the first `source_config` entry whose --<kind> arg is present."""
    if not profile.source_config:
        raise ValueError(
            f"profile {profile.name!r} does not declare any source_config"
        )

    if args.pcap:
        kind = "pcap"
        if kind not in profile.source_config:
            raise ValueError(
                f"profile {profile.name!r} does not accept kind='pcap'"
            )
        options = dict(profile.source_config[kind])
        return SourceSpec(kind=kind, uri=args.pcap, options=options)

    if args.log:
        kind = "log"
        if kind not in profile.source_config:
            raise ValueError(
                f"profile {profile.name!r} does not accept kind='log'"
            )
        options = dict(profile.source_config[kind])
        return SourceSpec(kind=kind, uri=args.log, options=options)

    raise ValueError("pass --pcap (for pcap profiles) or --log (for log profiles)")


__all__ = ["register", "run"]
