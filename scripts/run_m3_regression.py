"""
M3 regression baseline: run the Open5GS 5GC profile on every canonical
pcap fixture and snapshot the agent's output.

Unlike `run_m3_smoke.py`, this script has NO pass/fail gate. Its only
job is to produce a JSON report we can diff against future runs — a
reproducible baseline of what the current (profile, model) pair emits
for each capture.

The resulting JSON contains, per pcap:
  - ingest stats (record count, seq range)
  - kernel stats (rounds, tool calls, elapsed)
  - `final_json` verbatim (or null if the agent couldn't finalise)
  - the ordered list of tool call names
  - `stop_reason`

The script exits 0 as long as it finished; non-zero only on catastrophic
failure (bad env, kernel exception per capture is recorded and skipped).

Usage:

    # Full baseline against MiniMax-M2.7
    $env:OPENAI_API_KEY = (Get-Content minimax.txt -Raw).Trim()
    python -u scripts/run_m3_regression.py `
      --model "openai/MiniMax-M2.7" `
      --api-base "https://api.minimaxi.com/v1" `
      --temperature 0.2 `
      --report scripts/m3_regression_baseline.json

    # Sub-set: regenerate just the failure captures
    python -u scripts/run_m3_regression.py --filter "0[3-8]_*"

Requires `tshark` on PATH.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from traceweaver.core.intelligence import LLMIntelligence  # noqa: E402
from traceweaver.core.kernel import AgentKernel  # noqa: E402
from traceweaver.core.profile.runtime import (  # noqa: E402
    build_knowledge_store,
    ingest_for_profile,
)
from traceweaver.core.profile.yaml_loader import load_profile_from_dir  # noqa: E402
from traceweaver.core.source import SourceSpec  # noqa: E402
from traceweaver.builtin import (  # noqa: E402
    register_builtin_sources,
    register_builtin_tools,
)
from traceweaver.core.source.registry import SourceRegistry  # noqa: E402
from traceweaver.core.tools.loader import load_profile_tools  # noqa: E402
from traceweaver.core.tools.registry import ToolRegistry  # noqa: E402


PROFILE_ROOT = _ROOT / "traceweaver" / "profiles" / "open5gs_5gc"
PCAP_DIR = _ROOT / "tests" / "fixtures" / "pcap"

DEFAULT_PROMPT = (
    "This is a capture from an Open5GS 5G core. Diagnose what happened "
    "to the UE (or UEs) and return the required JSON verdict. Follow "
    "the workflow: start with summarize_capture, use its capture-wide "
    "signals to choose the right UE or NF path, then drill down with "
    "the other tools as needed. Every evidence entry must come from a "
    "tool result."
)


def _reconfigure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def _ingest_info(handle: Any) -> dict[str, Any]:
    try:
        meta = handle.metadata() or {}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"metadata: {type(exc).__name__}: {exc}"}
    return {
        "count": meta.get("count"),
        "seq_range": meta.get("seq_range"),
    }


def _pcap_source_spec(profile, pcap_path: Path) -> SourceSpec:
    options = dict(profile.source_config["pcap"])
    return SourceSpec(kind="pcap", uri=str(pcap_path), options=options)


def _tool_calls(result) -> list[str]:
    names: list[str] = []
    for ev in result.trace.events:
        for ex in ev.tool_executions:
            names.append(ex.call.name)
    return names


def run_one(
    pcap_path: Path,
    kernel: AgentKernel,
    profile,
    user_prompt: str,
    source_registry: SourceRegistry,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    entry: dict[str, Any] = {
        "pcap": pcap_path.name,
        "ok": True,
    }
    try:
        handle = ingest_for_profile(
            profile,
            _pcap_source_spec(profile, pcap_path),
            registry=source_registry,
        )
    except Exception as exc:  # noqa: BLE001
        entry.update(
            {
                "ok": False,
                "stage": "ingest",
                "error": f"{type(exc).__name__}: {exc}",
                "elapsed_s": round(time.perf_counter() - t0, 2),
            }
        )
        return entry

    entry["ingest"] = _ingest_info(handle)
    knowledge = build_knowledge_store(profile)

    try:
        result = kernel.run_with_profile(
            profile,
            user_request=user_prompt,
            source_handle=handle,
            knowledge_store=knowledge,
        )
    except Exception as exc:  # noqa: BLE001
        entry.update(
            {
                "ok": False,
                "stage": "kernel",
                "error": f"{type(exc).__name__}: {exc}",
                "elapsed_s": round(time.perf_counter() - t0, 2),
            }
        )
        return entry

    entry.update(
        {
            "stop_reason": result.stop_reason,
            "rounds_used": len(result.trace.events),
            "tool_calls_total": len(_tool_calls(result)),
            "calls": _tool_calls(result),
            "final_json": result.final_json,
            "elapsed_s": round(time.perf_counter() - t0, 2),
        }
    )
    return entry


def main() -> int:
    _reconfigure_stdio()

    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="openai/qwen/qwen3.5-9b")
    ap.add_argument("--api-base", default="http://127.0.0.1:1234/v1")
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument(
        "--filter",
        default="*.pcapng",
        help=(
            "fnmatch glob applied to pcap file name. Default *.pcapng "
            "runs everything in the fixture directory."
        ),
    )
    ap.add_argument(
        "--report",
        type=Path,
        default=_ROOT / "scripts" / "m3_regression_baseline.json",
    )
    ap.add_argument(
        "--user-prompt",
        default=DEFAULT_PROMPT,
        help="Override the user prompt sent to the agent.",
    )
    args = ap.parse_args()

    if shutil.which("tshark") is None:
        print("[M3-regression] ERROR: tshark not found on PATH.")
        return 2

    if not PCAP_DIR.is_dir():
        print(f"[M3-regression] ERROR: pcap dir missing: {PCAP_DIR}")
        return 2

    pcaps = sorted(
        p for p in PCAP_DIR.iterdir()
        if p.is_file() and fnmatch.fnmatch(p.name, args.filter)
    )
    if not pcaps:
        print(f"[M3-regression] no pcaps matched filter {args.filter!r}")
        return 0

    profile = load_profile_from_dir(PROFILE_ROOT)
    source_registry = SourceRegistry()
    register_builtin_sources(source_registry)
    registry = ToolRegistry()
    register_builtin_tools(registry)
    load_profile_tools(registry, profile.tools)
    intelligence = LLMIntelligence(
        model=args.model,
        api_base=args.api_base,
        temperature=args.temperature,
    )
    kernel = AgentKernel(intelligence=intelligence, tools=list(registry.values()))

    print(
        f"[M3-regression] model={args.model} api_base={args.api_base} "
        f"temp={args.temperature}",
        flush=True,
    )
    print(
        f"[M3-regression] profile={profile.name} pcaps={len(pcaps)}",
        flush=True,
    )

    entries: list[dict[str, Any]] = []
    t_all = time.perf_counter()
    for idx, pcap_path in enumerate(pcaps, 1):
        print(f"\n[{idx}/{len(pcaps)}] {pcap_path.name}", flush=True)
        entry = run_one(pcap_path, kernel, profile, args.user_prompt, source_registry)
        entries.append(entry)
        if entry["ok"]:
            verdict = (entry.get("final_json") or {}).get("verdict")
            print(
                f"  -> stop={entry.get('stop_reason')} verdict={verdict!r} "
                f"rounds={entry.get('rounds_used')} "
                f"tools={entry.get('tool_calls_total')} "
                f"({entry.get('elapsed_s')}s)",
                flush=True,
            )
        else:
            print(
                f"  -> ERROR at {entry.get('stage')}: {entry.get('error')} "
                f"({entry.get('elapsed_s')}s)",
                flush=True,
            )

    report = {
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "model": args.model,
        "api_base": args.api_base,
        "temperature": args.temperature,
        "profile": profile.name,
        "pcap_count": len(pcaps),
        "elapsed_s": round(time.perf_counter() - t_all, 2),
        "entries": entries,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"\n[M3-regression] baseline written to {args.report}", flush=True)
    print(
        f"[M3-regression] total elapsed: {report['elapsed_s']}s",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
