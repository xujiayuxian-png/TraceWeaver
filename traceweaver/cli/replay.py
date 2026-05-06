"""
`traceweaver replay` — replay a recorded LLM session for deterministic verification.

Loads a YAML recording produced by RecordReplayIntelligence in "record" mode
and replays it through the kernel, verifying that the same tool calls are made
and the same final output is produced — without hitting the LLM.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from traceweaver.core.kernel import AgentKernel, TaskSpec
from traceweaver.core.protocols import ToolContext
from traceweaver.core.profile.runtime import build_knowledge_store, ingest_for_profile
from traceweaver.core.source import SourceSpec
from traceweaver.builtin import register_builtin_sources, register_builtin_tools
from traceweaver.core.tools.registry import ToolRegistry
from traceweaver.core.tools.loader import load_profile_tools
from traceweaver.core.source.registry import SourceRegistry
from traceweaver.recording.recorder import RecordReplayIntelligence


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "replay",
        help="Replay a recorded LLM session for deterministic verification.",
    )
    p.add_argument(
        "--profile", required=True, help="Profile name or path"
    )
    p.add_argument(
        "--pcap", required=True, help="Path to pcap/pcapng used in the original recording"
    )
    p.add_argument(
        "--recording", required=True, help="Path to the YAML recording file"
    )
    p.add_argument(
        "--format",
        choices=["human", "json"],
        default="human",
        help="Output format (default: human)",
    )
    p.add_argument(
        "--expect-stop",
        default="final",
        help="Expected stop_reason (default: final)",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    recording_path = Path(args.recording)
    if not recording_path.is_file():
        print(f"error: recording not found: {recording_path}", file=sys.stderr)
        return 2

    from traceweaver.cli.analyze import _resolve_profile

    try:
        profile = _resolve_profile(args.profile)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: profile {args.profile!r}: {exc}", file=sys.stderr)
        return 2

    source_spec = SourceSpec(
        kind="pcap",
        uri=args.pcap,
        options=dict(profile.source_config.get("pcap", {})),
    )

    source_reg = SourceRegistry()
    register_builtin_sources(source_reg)
    try:
        handle = ingest_for_profile(profile, source_spec, registry=source_reg)
    except (FileNotFoundError, RuntimeError, ImportError) as exc:
        print(f"error: source ingest failed: {exc}", file=sys.stderr)
        return 3

    knowledge = build_knowledge_store(profile)

    tool_reg = ToolRegistry()
    register_builtin_tools(tool_reg)
    try:
        load_profile_tools(tool_reg, profile.tools)
    except (ImportError, AttributeError, TypeError, ValueError) as exc:
        print(f"error: profile tool loading failed: {exc}", file=sys.stderr)
        return 2
    tools = list(tool_reg.values())

    replay_intel = RecordReplayIntelligence(
        inner=None, recording_path=recording_path, mode="replay"
    )
    kernel = AgentKernel(intelligence=replay_intel, tools=tools)

    llm = profile.llm
    task = TaskSpec(
        system_prompt=llm.system_prompt or "",
        max_rounds=llm.max_rounds or 5,
        response_schema=llm.response_schema,
    )
    ctx = ToolContext(
        source_handle=handle, knowledge_store=knowledge, profile_name=profile.name
    )

    question = "Replay from recording"
    try:
        result = kernel.run(task, question, ctx)
    except IndexError as exc:
        print(f"error: replay failed — {exc}", file=sys.stderr)
        return 4

    if args.format == "json":
        print(
            json.dumps(
                {
                    "stop_reason": result.stop_reason,
                    "rounds_used": len(result.trace.events),
                    "tool_calls_total": sum(
                        len(ev.tool_executions) for ev in result.trace.events
                    ),
                    "final_json": result.final_json,
                    "final_text": result.final_text,
                    "error": result.error,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        rounds = len(result.trace.events)
        calls = sum(len(ev.tool_executions) for ev in result.trace.events)
        print(f"Replay complete: stop_reason={result.stop_reason}, "
              f"rounds={rounds}, tool_calls={calls}")
        if result.final_json:
            print(json.dumps(result.final_json, ensure_ascii=False, indent=2))
        elif result.final_text:
            print(result.final_text)
        if result.error:
            print(f"Error: {result.error}", file=sys.stderr)

    if result.stop_reason != args.expect_stop:
        print(
            f"FAIL: expected stop_reason={args.expect_stop!r}, "
            f"got {result.stop_reason!r}",
            file=sys.stderr,
        )
        return 1

    return 0


__all__ = ["register", "run"]
