"""
M2 smoke test: drive AgentKernel.run_with_profile through a handful of
tasks using ONLY the built-in tools (`query_records`,
`get_records_around`, `search_knowledge`) against a FakeSource and the
minimal test profile's knowledge base.

Passing this script is the M2 exit criterion. It verifies that:

  - Profile / FileKnowledgeStore / SourceHandle plumbing reach the
    kernel as a usable ToolContext,
  - the LLM can drive the built-in tools to answer questions grounded
    in the source records (not hallucinated),
  - the knowledge-store hint in `search_knowledge` keeps the model from
    looping on missing entries.

Usage (Windows PowerShell, LM Studio baseline):

    .venv\\Scripts\\python scripts\\run_m2_smoke.py \\
        --model openai/qwen/qwen3.5-9b \\
        --api-base http://127.0.0.1:1234/v1

The script exits 0 if every task passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
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
from traceweaver.core.knowledge import FileKnowledgeStore  # noqa: E402
from traceweaver.core.profile import load_profile_from_dir  # noqa: E402
from traceweaver.core.source import Record, SourceSpec  # noqa: E402
from traceweaver.core.source.fake import FakeSource  # noqa: E402
from traceweaver.core.tools.builtin import register_builtin_tools  # noqa: E402
from traceweaver.core.tools.registry import ToolRegistry  # noqa: E402


FIXTURE_PROFILE = _ROOT / "tests" / "fixtures" / "profiles" / "minimal"


# ---------------------------------------------------------------
# Fake 5GC-ish records: four frames that tell a small story the
# LLM must reconstruct by calling tools rather than guessing.
# ---------------------------------------------------------------

def build_records() -> list[Record]:
    base_ts = 1_700_000_000.0
    rows = [
        (1, "REGISTRATION_REQUEST", "", 100, 0, ""),
        (2, "AUTHENTICATION_REQUEST", "", 100, 200, ""),
        (3, "AUTHENTICATION_FAILURE", "MAC_FAILURE", 100, 200, "cause=20"),
        (4, "REGISTRATION_REJECT", "cause_20", 100, 200, "cause=20"),
    ]
    records: list[Record] = []
    for seq, event, result, ran_id, amf_id, note in rows:
        records.append(
            Record(
                source="fake",
                timestamp=base_ts + seq * 0.1,
                seq=seq,
                key=f"ran={ran_id}|amf={amf_id}",
                fields={
                    "event": event,
                    "result": result,
                    "ran_ue_ngap_id": ran_id,
                    "amf_ue_ngap_id": amf_id,
                    "note": note,
                },
                raw=f"frame {seq} {event} {note}",
            )
        )
    return records


# ---------------------------------------------------------------
# Task definitions
# ---------------------------------------------------------------

CheckFn = Callable[[AgentResult], tuple[bool, str]]


@dataclass(frozen=True)
class SmokeTask:
    name: str
    description: str
    user_prompt: str
    check: CheckFn
    response_schema: dict[str, Any] | None = None


def _called(result: AgentResult, name: str) -> bool:
    return result.trace.called(name)


def _all_tool_calls(result: AgentResult) -> list[str]:
    names: list[str] = []
    for ev in result.trace.events:
        for ex in ev.tool_executions:
            names.append(ex.call.name)
    return names


def _check_query_records_count(result: AgentResult) -> tuple[bool, str]:
    if result.stop_reason != "final":
        return False, f"did not reach final (stop_reason={result.stop_reason})"
    if not _called(result, "query_records"):
        return False, "expected to call query_records"
    fj = result.final_json or {}
    if not isinstance(fj, dict) or "answer" not in fj:
        return False, f"final output missing 'answer': {fj}"
    text = str(fj["answer"]).lower()
    if "4" not in text and "four" not in text:
        return False, f"answer should mention 4 records, got: {fj['answer']!r}"
    return True, "ok"


def _check_find_reject_frame(result: AgentResult) -> tuple[bool, str]:
    if result.stop_reason != "final":
        return False, f"did not reach final (stop_reason={result.stop_reason})"
    if not _called(result, "query_records"):
        return False, "expected to call query_records"
    fj = result.final_json or {}
    if "seq" not in fj:
        return False, f"final JSON missing 'seq' field: {fj}"
    try:
        if int(fj["seq"]) != 4:
            return False, f"expected seq=4, got {fj['seq']!r}"
    except (TypeError, ValueError):
        return False, f"seq must be an integer-like value: {fj['seq']!r}"
    return True, "ok"


def _check_around_authfailure(result: AgentResult) -> tuple[bool, str]:
    if result.stop_reason != "final":
        return False, f"did not reach final (stop_reason={result.stop_reason})"
    calls = _all_tool_calls(result)
    if "get_records_around" not in calls:
        return False, f"expected to call get_records_around; calls={calls}"
    fj = result.final_json or {}
    if "neighbors" not in fj:
        return False, f"final JSON missing 'neighbors': {fj}"
    neighbors = fj["neighbors"]
    if not isinstance(neighbors, list) or len(neighbors) < 2:
        return False, f"expected >=2 neighbors, got {neighbors!r}"
    return True, "ok"


def _check_knowledge_hit(result: AgentResult) -> tuple[bool, str]:
    if result.stop_reason != "final":
        return False, f"did not reach final (stop_reason={result.stop_reason})"
    if not _called(result, "search_knowledge"):
        return False, "expected to call search_knowledge"
    fj = result.final_json or {}
    answer = str(fj.get("answer", "")).strip().lower()
    if len(answer) < 15:
        return False, f"answer looks empty / placeholder: {fj.get('answer')!r}"
    expected_tokens = ("cell", "coverage", "cause", "reject", "rf", "register")
    if not any(tok in answer for tok in expected_tokens):
        return False, (
            f"answer should reflect the Registration Reject section; "
            f"got {fj.get('answer')!r}"
        )
    return True, "ok"


def _check_knowledge_miss_no_loop(result: AgentResult) -> tuple[bool, str]:
    if result.stop_reason != "final":
        return False, f"did not reach final (stop_reason={result.stop_reason})"
    calls = _all_tool_calls(result)
    sk = [c for c in calls if c == "search_knowledge"]
    if len(sk) == 0:
        return False, "expected at least one search_knowledge call"
    if len(sk) > 2:
        return False, f"search_knowledge called {len(sk)} times; the no-match hint should stop the loop"
    fj = result.final_json or {}
    if "answer" not in fj:
        return False, f"final JSON missing 'answer': {fj}"
    return True, "ok"


def build_tasks() -> list[SmokeTask]:
    return [
        SmokeTask(
            name="T1_source_count",
            description="Count records in the source",
            user_prompt=(
                "Use query_records with an empty filter and limit=500 to "
                "inspect the source, then tell me how many records it has. "
                "Reply with a single JSON object of the form "
                '{"answer": "there are N records"}. Call query_records at most once.'
            ),
            check=_check_query_records_count,
            response_schema={"type": "object", "required": ["answer"]},
        ),
        SmokeTask(
            name="T2_find_reject",
            description="Find the REGISTRATION_REJECT record's seq",
            user_prompt=(
                "Find the record whose event equals 'REGISTRATION_REJECT' "
                "and return its seq number. Reply with a JSON object of "
                'the form {"seq": 4} (replace 4 with the actual seq).'
            ),
            check=_check_find_reject_frame,
            response_schema={"type": "object", "required": ["seq"]},
        ),
        SmokeTask(
            name="T3_around_authfailure",
            description="Get the records around the AUTHENTICATION_FAILURE",
            user_prompt=(
                "First find the seq of the AUTHENTICATION_FAILURE record "
                "with query_records. Then call get_records_around with "
                "before=1 and after=1 using that seq as the anchor. "
                "Finally, reply with a JSON object of the form "
                '{"neighbors": [2, 3, 4]} listing the seq numbers of the '
                "returned window in order."
            ),
            check=_check_around_authfailure,
            response_schema={"type": "object", "required": ["neighbors"]},
        ),
        SmokeTask(
            name="T4_knowledge_hit",
            description="Search knowledge for 'registration reject'",
            user_prompt=(
                "Search the profile's knowledge base for 'registration "
                "reject' and summarize the matching section in one "
                "sentence of your own words. Reply with a JSON object "
                'like {"answer": "Your one-sentence summary here."}.'
            ),
            check=_check_knowledge_hit,
            response_schema={"type": "object", "required": ["answer"]},
        ),
        SmokeTask(
            name="T5_knowledge_miss",
            description="Knowledge miss should not loop",
            user_prompt=(
                "Search the knowledge base for 'zzz-unlikely-term-xxx'. "
                "If there is no match, trust the hint and stop searching; "
                "answer from general knowledge. Reply with a JSON object "
                'like {"answer": "No entry exists; here is my best general answer."}.'
            ),
            check=_check_knowledge_miss_no_loop,
            response_schema={"type": "object", "required": ["answer"]},
        ),
    ]


# ---------------------------------------------------------------
# Runner
# ---------------------------------------------------------------


def run_task(
    task: SmokeTask,
    kernel: AgentKernel,
    profile,
    source_handle,
    knowledge_store,
) -> tuple[bool, str, dict[str, Any]]:
    t0 = time.perf_counter()
    try:
        result = kernel.run_with_profile(
            profile,
            user_request=task.user_prompt,
            source_handle=source_handle,
            knowledge_store=knowledge_store,
            response_schema=task.response_schema,
        )
    except Exception as exc:  # noqa: BLE001
        return (
            False,
            f"exception: {type(exc).__name__}: {exc}",
            {"elapsed_s": time.perf_counter() - t0},
        )
    ok, reason = task.check(result)
    info = {
        "stop_reason": result.stop_reason,
        "final_json": result.final_json,
        "calls": _all_tool_calls(result),
        "events": [ev.model_dump(mode="json") for ev in result.trace.events],
        "elapsed_s": round(time.perf_counter() - t0, 2),
    }
    return ok, reason, info


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="openai/qwen/qwen3.5-9b")
    ap.add_argument("--api-base", default="http://127.0.0.1:1234/v1")
    ap.add_argument("--report", type=Path, default=None)
    ap.add_argument(
        "--only",
        action="append",
        default=[],
        help="Run only tasks with this name (repeatable).",
    )
    args = ap.parse_args()

    profile = load_profile_from_dir(FIXTURE_PROFILE)
    source_handle = FakeSource().ingest(
        SourceSpec(
            kind="fake",
            uri="memory://m2-smoke",
            options={"records_object": build_records()},
        )
    )
    knowledge_store = FileKnowledgeStore(items=profile.knowledge)

    registry = ToolRegistry()
    register_builtin_tools(registry)

    intelligence = LLMIntelligence(
        model=args.model,
        api_base=args.api_base,
    )
    kernel = AgentKernel(intelligence=intelligence, registry=registry)

    tasks = build_tasks()
    if args.only:
        wanted = set(args.only)
        tasks = [t for t in tasks if t.name in wanted]

    results: list[dict[str, Any]] = []
    passed = 0
    print(f"[M2-smoke] model={args.model} api_base={args.api_base}")
    print(f"[M2-smoke] profile={profile.name} records={source_handle.metadata()['count']}")
    for task in tasks:
        print(f"\n[{task.name}] {task.description}")
        ok, reason, info = run_task(
            task, kernel, profile, source_handle, knowledge_store
        )
        status = "PASS" if ok else "FAIL"
        print(f"  -> {status} ({info.get('elapsed_s', '?')}s)  {reason}")
        if not ok:
            print(f"     final_json={info.get('final_json')!r}")
            print(f"     calls={info.get('calls')}")
        results.append(
            {
                "task": task.name,
                "description": task.description,
                "ok": ok,
                "reason": reason,
                **info,
            }
        )
        if ok:
            passed += 1

    summary = {
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "model": args.model,
        "api_base": args.api_base,
        "passed": passed,
        "total": len(tasks),
        "results": results,
    }
    print(f"\n[M2-smoke] {passed}/{len(tasks)} tasks passed")

    if args.report is not None:
        args.report.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"[M2-smoke] report written to {args.report}")

    return 0 if passed == len(tasks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
