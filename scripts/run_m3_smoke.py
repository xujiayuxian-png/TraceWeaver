"""
M3 smoke test: drive the Open5GS 5GC profile on five canonical pcaps.

Passing this script 5/5 is the M3 exit criterion. It verifies that:

  - `traceweaver.profiles.open5gs_5gc` loads end-to-end via the yaml
    loader + tool loader + enricher.
  - PcapSource ingests a real capture, the enricher annotates events
    correctly, and the five profile tools dispatch against the result.
  - `AgentKernel.run_with_profile` + `LLMIntelligence` on the Qwen3.5
    baseline produces a JSON verdict that matches the canonical
    expectation for each pcap (success / failure + dominant cause).

Requires `tshark` on PATH and an LM Studio server serving Qwen3.5-9b
on `http://127.0.0.1:1234/v1` (override with flags).

The script exits 0 if every task passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from traceweaver.core.intelligence import LLMIntelligence  # noqa: E402
from traceweaver.core.kernel import AgentKernel, AgentResult  # noqa: E402
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


# --- task expectations -----------------------------------------------

CheckFn = Callable[[AgentResult], tuple[bool, str]]


@dataclass(frozen=True)
class SmokeTask:
    name: str
    pcap: str
    description: str
    user_prompt: str
    check: CheckFn


def _all_tool_calls(result: AgentResult) -> list[str]:
    names: list[str] = []
    for ev in result.trace.events:
        for ex in ev.tool_executions:
            names.append(ex.call.name)
    return names


def _final(result: AgentResult) -> dict[str, Any]:
    return result.final_json or {}


def _require_final(result: AgentResult) -> tuple[bool, str]:
    if result.stop_reason != "final":
        return False, f"did not reach final (stop_reason={result.stop_reason})"
    return True, ""


def _check_01_registration_success(result: AgentResult) -> tuple[bool, str]:
    ok, msg = _require_final(result)
    if not ok:
        return False, msg
    fj = _final(result)
    if fj.get("verdict") != "success":
        return False, f"expected verdict=success, got {fj.get('verdict')!r}"
    return True, "ok"


def _check_03_registration_reject(result: AgentResult) -> tuple[bool, str]:
    ok, msg = _require_final(result)
    if not ok:
        return False, msg
    fj = _final(result)
    if fj.get("verdict") != "failure":
        return False, f"expected verdict=failure, got {fj.get('verdict')!r}"
    evidence = fj.get("evidence") or []
    events = {str(ev.get("event", "")).upper() for ev in evidence}
    if not any("REJECT" in e for e in events):
        return False, f"expected REJECT in evidence events, got {events}"
    return True, "ok"


def _check_04_authentication_failure(result: AgentResult) -> tuple[bool, str]:
    ok, msg = _require_final(result)
    if not ok:
        return False, msg
    fj = _final(result)
    if fj.get("verdict") != "failure":
        return False, f"expected verdict=failure, got {fj.get('verdict')!r}"
    rc = str(fj.get("root_cause") or "").lower()
    summary = str(fj.get("summary") or "").lower()
    signals = ("mac", "authentic", "20", "aka")
    if not any(sig in rc or sig in summary for sig in signals):
        return False, (
            f"expected authentication / MAC failure cue in root_cause/summary; "
            f"got root_cause={rc!r} summary={summary!r}"
        )
    return True, "ok"


def _check_07_pfcp_failure(result: AgentResult) -> tuple[bool, str]:
    ok, msg = _require_final(result)
    if not ok:
        return False, msg
    fj = _final(result)
    if fj.get("verdict") not in ("failure", "unclear"):
        return False, f"expected verdict in {{failure, unclear}}, got {fj.get('verdict')!r}"
    calls = _all_tool_calls(result)
    text = " ".join(
        [
            str(fj.get("summary") or ""),
            str(fj.get("root_cause") or ""),
            str(fj.get("failure_point") or ""),
        ]
    ).lower()
    pfcp_mentioned = (
        "pfcp" in text or "upf" in text or "get_pfcp_exchanges" in calls
    )
    if not pfcp_mentioned:
        return False, (
            "expected PFCP / UPF cue in diagnosis (either text mention or "
            f"get_pfcp_exchanges call); calls={calls}"
        )
    return True, "ok"


def _check_08_sbi_failure(result: AgentResult) -> tuple[bool, str]:
    ok, msg = _require_final(result)
    if not ok:
        return False, msg
    fj = _final(result)
    if fj.get("verdict") not in ("failure", "unclear"):
        return False, f"expected verdict in {{failure, unclear}}, got {fj.get('verdict')!r}"
    calls = _all_tool_calls(result)
    text = " ".join(
        [
            str(fj.get("summary") or ""),
            str(fj.get("root_cause") or ""),
            str(fj.get("failure_point") or ""),
        ]
    ).lower()
    sbi_mentioned = (
        "sbi" in text
        or "http" in text
        or "ausf" in text
        or "udm" in text
        or "nausf" in text
        or "nudm" in text
        or "get_sbi_calls" in calls
    )
    if not sbi_mentioned:
        return False, (
            "expected SBI / HTTP / AUSF / UDM cue in diagnosis; "
            f"calls={calls}"
        )
    return True, "ok"


def _check_02_registration_and_pdu_success(result: AgentResult) -> tuple[bool, str]:
    """Registration + PDU session establishment success."""
    ok, msg = _require_final(result)
    if not ok:
        return False, msg
    fj = _final(result)
    if fj.get("verdict") != "success":
        return False, f"expected verdict=success, got {fj.get('verdict')!r}"
    calls = _all_tool_calls(result)
    # Should use PDU session related tools
    if not any("pdu" in c.lower() or "session" in c.lower() for c in calls):
        return False, f"expected PDU/session tool usage, got calls={calls}"
    return True, "ok"


def _check_05_pdu_session_reject(result: AgentResult) -> tuple[bool, str]:
    """PDU session establishment reject (e.g., insufficient resources)."""
    ok, msg = _require_final(result)
    if not ok:
        return False, msg
    fj = _final(result)
    if fj.get("verdict") not in ("failure", "unclear"):
        return False, f"expected verdict in {{failure, unclear}}, got {fj.get('verdict')!r}"
    # Evidence should mention PDU session reject or 5GSM cause
    evidence = fj.get("evidence") or []
    text = " ".join(str(e.get("event", "")).lower() for e in evidence)
    if "pdu" not in text and "session" not in text and "5gsm" not in text:
        return False, f"expected PDU session or 5GSM reference in evidence, got {evidence}"
    return True, "ok"


def _check_10_deregistration(result: AgentResult) -> tuple[bool, str]:
    """Clean deregistration - verdict success with deregistration evidence."""
    ok, msg = _require_final(result)
    if not ok:
        return False, msg
    fj = _final(result)
    if fj.get("verdict") != "success":
        return False, f"expected verdict=success for clean deregistration, got {fj.get('verdict')!r}"
    evidence = fj.get("evidence") or []
    text = " ".join(str(e.get("event", "")).lower() for e in evidence)
    if "deregist" not in text:
        return False, f"expected deregistration evidence, got {evidence}"
    return True, "ok"


def _check_11_registration_retry(result: AgentResult) -> tuple[bool, str]:
    """Registration with retry - eventual success after initial reject/failure."""
    ok, msg = _require_final(result)
    if not ok:
        return False, msg
    fj = _final(result)
    # Retry scenario: eventual success
    if fj.get("verdict") != "success":
        return False, f"expected eventual success after retry, got {fj.get('verdict')!r}"
    return True, "ok"


# --- task catalogue --------------------------------------------------

def build_tasks() -> list[SmokeTask]:
    common_prompt = (
        "This is a capture from an Open5GS 5G core. Diagnose what "
        "happened to the UE (or UEs) and return the required JSON "
        "verdict. Follow the workflow: start with summarize_capture, "
        "use its capture-wide signals to choose the right UE or NF path, "
        "then drill down with the other tools as needed. Every "
        "evidence entry must come from a tool result."
    )
    return [
        SmokeTask(
            name="T1_registration_success",
            pcap="01_registration_success.pcapng",
            description="Clean registration: verdict must be success.",
            user_prompt=common_prompt,
            check=_check_01_registration_success,
        ),
        SmokeTask(
            name="T2_registration_reject",
            pcap="03_registration_reject.pcapng",
            description="REGISTRATION_REJECT; evidence must include the reject frame.",
            user_prompt=common_prompt,
            check=_check_03_registration_reject,
        ),
        SmokeTask(
            name="T3_authentication_failure",
            pcap="04_authentication_failure.pcapng",
            description="AUTHENTICATION_FAILURE (MAC). Root cause must mention MAC/authentication.",
            user_prompt=common_prompt,
            check=_check_04_authentication_failure,
        ),
        SmokeTask(
            name="T4_pfcp_failure",
            pcap="07_pfcp_failure.pcapng",
            description="UPF unreachable; diagnosis must reach PFCP/UPF.",
            user_prompt=common_prompt,
            check=_check_07_pfcp_failure,
        ),
        SmokeTask(
            name="T5_sbi_failure",
            pcap="08_sbi_failure.pcapng",
            description="SBI failure (AUSF down); diagnosis must reach SBI / HTTP / AUSF.",
            user_prompt=common_prompt,
            check=_check_08_sbi_failure,
        ),
        # Extended tasks for better coverage (P0-1.1)
        SmokeTask(
            name="T6_registration_pdu_success",
            pcap="02_registration_and_pdu_session_success.pcapng",
            description="Registration + PDU session success: full flow.",
            user_prompt=common_prompt,
            check=_check_02_registration_and_pdu_success,
        ),
        SmokeTask(
            name="T7_pdu_session_reject",
            pcap="05_pdu_session_reject.pcapng",
            description="PDU session establishment reject.",
            user_prompt=common_prompt,
            check=_check_05_pdu_session_reject,
        ),
        SmokeTask(
            name="T8_deregistration",
            pcap="10_deregistration.pcapng",
            description="Clean deregistration flow.",
            user_prompt=common_prompt,
            check=_check_10_deregistration,
        ),
        SmokeTask(
            name="T9_registration_retry",
            pcap="11_registration_retry.pcapng",
            description="Registration with retry (eventual success).",
            user_prompt=common_prompt,
            check=_check_11_registration_retry,
        ),
    ]


# --- runner ----------------------------------------------------------

def _pcap_source_spec(profile, pcap_path: Path) -> SourceSpec:
    options = dict(profile.source_config["pcap"])
    return SourceSpec(kind="pcap", uri=str(pcap_path), options=options)


def run_task(
    task: SmokeTask,
    kernel: AgentKernel,
    profile,
    source_registry: SourceRegistry,
) -> tuple[bool, str, dict[str, Any]]:
    pcap_path = PCAP_DIR / task.pcap
    if not pcap_path.is_file():
        return (
            False,
            f"pcap fixture missing: {pcap_path}",
            {"elapsed_s": 0.0},
        )

    t0 = time.perf_counter()
    try:
        handle = ingest_for_profile(
            profile,
            _pcap_source_spec(profile, pcap_path),
            registry=source_registry,
        )
    except (FileNotFoundError, RuntimeError) as exc:
        return (
            False,
            f"ingest failed: {type(exc).__name__}: {exc}",
            {"elapsed_s": round(time.perf_counter() - t0, 2)},
        )

    knowledge = build_knowledge_store(profile)

    try:
        result = kernel.run_with_profile(
            profile,
            user_request=task.user_prompt,
            source_handle=handle,
            knowledge_store=knowledge,
        )
    except Exception as exc:  # noqa: BLE001
        return (
            False,
            f"kernel exception: {type(exc).__name__}: {exc}",
            {"elapsed_s": round(time.perf_counter() - t0, 2)},
        )

    ok, reason = task.check(result)
    info = {
        "stop_reason": result.stop_reason,
        "final_json": result.final_json,
        "calls": _all_tool_calls(result),
        "rounds_used": len(result.trace.events),
        "tool_calls_total": len(_all_tool_calls(result)),
        "elapsed_s": round(time.perf_counter() - t0, 2),
        # P1.1 telemetry
        "total_tokens": result.total_tokens,
        "total_cost_usd": result.total_cost_usd,
        "wall_clock_s": round(result.wall_clock_s, 2) if result.wall_clock_s else None,
    }
    return ok, reason, info


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="openai/qwen/qwen3.5-9b")
    ap.add_argument("--api-base", default="http://127.0.0.1:1234/v1")
    ap.add_argument(
        "--temperature",
        type=float,
        default=0.0,
        help=(
            "Sampling temperature. Local Qwen: 0.0 is fine. Hosted "
            "providers (e.g. MiniMax) may require temperature > 0."
        ),
    )
    ap.add_argument("--report", type=Path, default=None)
    ap.add_argument(
        "--only",
        action="append",
        default=[],
        help="Run only tasks with this name (repeatable).",
    )
    args = ap.parse_args()

    if shutil.which("tshark") is None:
        print("[M3-smoke] ERROR: tshark not found on PATH; install Wireshark first.")
        return 2

    profile = load_profile_from_dir(PROFILE_ROOT)
    source_registry = SourceRegistry()
    register_builtin_sources(source_registry)
    registry = ToolRegistry()
    register_builtin_tools(registry)
    load_profile_tools(registry, profile.tools)
    tools = list(registry.values())
    intelligence = LLMIntelligence(
        model=args.model,
        api_base=args.api_base,
        temperature=args.temperature,
    )
    kernel = AgentKernel(intelligence=intelligence, tools=tools)

    tasks = build_tasks()
    if args.only:
        wanted = set(args.only)
        tasks = [t for t in tasks if t.name in wanted]

    results: list[dict[str, Any]] = []
    passed = 0
    print(f"[M3-smoke] model={args.model} api_base={args.api_base}", flush=True)
    print(
        f"[M3-smoke] profile={profile.name} tools={len(profile.tools)} "
        f"enrichers={len(profile.enrichers)}",
        flush=True,
    )
    for task in tasks:
        print(f"\n[{task.name}] {task.description}", flush=True)
        print(f"  pcap: {task.pcap}", flush=True)
        ok, reason, info = run_task(task, kernel, profile, source_registry)
        status = "PASS" if ok else "FAIL"
        # P1.1: surface telemetry inline so operators can see real cost.
        tokens = info.get("total_tokens")
        cost = info.get("total_cost_usd")
        tele = ""
        if tokens is not None:
            tele = f"  tokens={tokens}"
            if cost is not None and cost > 0:
                tele += f" cost=${cost:.4f}"
        print(
            f"  -> {status} ({info.get('elapsed_s', '?')}s) "
            f"rounds={info.get('rounds_used')} tools={info.get('tool_calls_total')}"
            f"{tele}  {reason}",
            flush=True,
        )
        if not ok:
            print(f"     final_json={info.get('final_json')!r}", flush=True)
            print(f"     calls={info.get('calls')}", flush=True)
        results.append(
            {
                "task": task.name,
                "pcap": task.pcap,
                "description": task.description,
                "ok": ok,
                "reason": reason,
                **info,
            }
        )
        if ok:
            passed += 1

    # P1.1: aggregate telemetry across all tasks
    agg_tokens = sum(r.get("total_tokens") or 0 for r in results)
    agg_cost = sum(r.get("total_cost_usd") or 0.0 for r in results)
    agg_wall = sum(r.get("wall_clock_s") or 0.0 for r in results)
    summary = {
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "model": args.model,
        "api_base": args.api_base,
        "passed": passed,
        "total": len(tasks),
        "total_tokens": agg_tokens or None,
        "total_cost_usd": round(agg_cost, 4) if agg_cost else None,
        "total_wall_clock_s": round(agg_wall, 2),
        "results": results,
    }
    print(f"\n[M3-smoke] {passed}/{len(tasks)} tasks passed")
    if agg_tokens:
        cost_str = f" cost=${agg_cost:.4f}" if agg_cost > 0 else ""
        print(
            f"[M3-smoke] telemetry: tokens={agg_tokens}{cost_str} "
            f"wall_clock={agg_wall:.1f}s"
        )

    if args.report is not None:
        args.report.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"[M3-smoke] report written to {args.report}")

    return 0 if passed == len(tasks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
