"""
M1 smoke test: drive the real `AgentKernel` + `LLMIntelligence` stack
through the same five baseline tool-calling tasks that
`scripts/validate_tool_calling.py` uses.

The difference from `validate_tool_calling.py` is that this script goes
through the full v2 Layer 2/3/4 contracts:

    ToolRegistry  <-- AgentKernel -->  LLMIntelligence  --litellm-->  provider

Passing this script is the M1 exit criterion. The old script stays
around as a single-call sanity check that bypasses the kernel.

Usage (Windows PowerShell, LM Studio baseline):

    .venv\\Scripts\\python scripts\\run_m1_smoke.py \\
        --model openai/qwen/qwen3.5-9b \\
        --api-base http://127.0.0.1:1234/v1
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

# ensure project root is importable when running the script directly
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from traceweaver.core.intelligence import LLMIntelligence  # noqa: E402
from traceweaver.core.kernel import AgentKernel, AgentResult, TaskSpec  # noqa: E402
from traceweaver.core.tools import Tool, ToolContext, ToolRegistry, ToolResult, ToolSpec  # noqa: E402


# ============================================================
# Mock data (mirrors scripts/validate_tool_calling.py fixtures)
# ============================================================

SESSIONS = [
    {
        "index": 0,
        "session_id": "ue-session-1",
        "ran_ue_ngap_id": 100,
        "amf_ue_ngap_id": 200,
        "events": ["REGISTRATION_REQUEST", "AUTHENTICATION_FAILURE"],
    },
    {
        "index": 1,
        "session_id": "ue-session-2",
        "ran_ue_ngap_id": 101,
        "amf_ue_ngap_id": 201,
        "events": ["REGISTRATION_REQUEST", "REGISTRATION_ACCEPT"],
    },
]

FRAMES = {
    42: {
        "frame_number": 42,
        "event": "AUTHENTICATION_FAILURE",
        "cause_code": 20,
        "session_index": 0,
    }
}

KNOWLEDGE = {
    "cause 20": (
        "5GMM cause 20 (MAC failure): the MAC in the AUTHENTICATION RESPONSE "
        "was incorrect. Typical root cause: SIM-side key (K) mismatch with "
        "UDM subscription."
    ),
}


# ============================================================
# Tools
# ============================================================


class GetSessionCountTool(Tool):
    spec = ToolSpec(
        name="get_session_count",
        description="Return how many UE sessions exist in the capture.",
        parameters_schema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        return ToolResult(data={"count": len(SESSIONS)})


class GetSessionInfoTool(Tool):
    spec = ToolSpec(
        name="get_session_info",
        description="Get details of a specific session by index.",
        parameters_schema={
            "type": "object",
            "properties": {
                "session_index": {
                    "type": "integer",
                    "description": "0-based index of the session",
                    "minimum": 0,
                }
            },
            "required": ["session_index"],
        },
    )

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        idx = kwargs["session_index"]
        if not isinstance(idx, int) or idx < 0 or idx >= len(SESSIONS):
            return ToolResult(data={"error": f"session_index {idx} out of range"})
        return ToolResult(data=dict(SESSIONS[idx]))


class GetFrameAtTool(Tool):
    spec = ToolSpec(
        name="get_frame_at",
        description="Get the raw frame record at a specific frame number.",
        parameters_schema={
            "type": "object",
            "properties": {
                "frame_number": {
                    "type": "integer",
                    "description": "1-based frame number as in tshark output",
                    "minimum": 1,
                }
            },
            "required": ["frame_number"],
        },
    )

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        fn = kwargs["frame_number"]
        if fn in FRAMES:
            return ToolResult(data=dict(FRAMES[fn]))
        return ToolResult(data={"error": f"frame {fn} not found"})


class SearchKnowledgeTool(Tool):
    spec = ToolSpec(
        name="search_knowledge",
        description="Search the 3GPP knowledge base for cause codes or procedures.",
        parameters_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Free-text query",
                }
            },
            "required": ["query"],
        },
    )

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        q = (kwargs.get("query") or "").lower()
        for key, val in KNOWLEDGE.items():
            tokens = [t for t in key.split() if t]
            if tokens and all(t in q for t in tokens):
                return ToolResult(data={"result": val})
        return ToolResult(
            data={
                "result": "no matching entry",
                "hint": (
                    "The knowledge base has no relevant entry for this query. "
                    "Do not keep searching — proceed with your best diagnosis "
                    "using general knowledge and the data already gathered."
                ),
            }
        )


class EchoTool(Tool):
    spec = ToolSpec(
        name="echo",
        description=(
            "A debug-only tool that echoes the input. DO NOT call this unless "
            "the user explicitly asks you to test echoing. It has no diagnostic value."
        ),
        parameters_schema={
            "type": "object",
            "properties": {
                "text": {"type": "string"},
            },
            "required": ["text"],
        },
    )

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        return ToolResult(data={"echoed": kwargs.get("text", "")})


def build_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register_all(
        [
            GetSessionCountTool(),
            GetSessionInfoTool(),
            GetFrameAtTool(),
            SearchKnowledgeTool(),
            EchoTool(),
        ]
    )
    return reg


# ============================================================
# Tasks
# ============================================================


CheckFn = Callable[[AgentResult], tuple[bool, str]]


@dataclass(frozen=True)
class SmokeTask:
    name: str
    description: str
    system_prompt: str
    user_prompt: str
    check: CheckFn
    response_schema: dict[str, Any] | None = None


def _called(result: AgentResult, name: str) -> bool:
    return result.trace.called(name)


def _total_tool_calls(result: AgentResult) -> int:
    return result.trace.tool_calls_total()


def _called_with(
    result: AgentResult, name: str, predicate: Callable[[dict], bool]
) -> bool:
    for ev in result.trace.events:
        for ex in ev.tool_executions:
            if ex.call.name == name and predicate(ex.call.arguments):
                return True
    return False


def check_t1(r: AgentResult) -> tuple[bool, str]:
    total = _total_tool_calls(r)
    if total == 0:
        return False, "expected to call get_session_count"
    if _called(r, "echo"):
        return False, "should not call echo tool"
    if not _called(r, "get_session_count"):
        return False, "expected get_session_count"
    if total > 1:
        names = [
            ex.call.name for ev in r.trace.events for ex in ev.tool_executions
        ]
        return False, f"expected exactly 1 tool call, got {total}: {names}"
    text = r.final_text or json.dumps(r.final_json or {}, ensure_ascii=False)
    if "2" not in text:
        return False, f"final answer should mention the count (2), got: {text[:200]}"
    return True, "ok"


def check_t2(r: AgentResult) -> tuple[bool, str]:
    if _called(r, "echo"):
        return False, "should NOT call echo tool to emit the final JSON"
    if not isinstance(r.final_json, dict):
        return False, f"final output is not a dict: {r.final_text!r}"
    verdict = r.final_json.get("verdict")
    if verdict not in ("OK", "FAIL", "INCONCLUSIVE"):
        return False, f"verdict not in enum: {verdict!r}"
    if verdict != "FAIL":
        return False, (
            f"expected verdict=FAIL (session 0 has AUTHENTICATION_FAILURE), "
            f"got {verdict!r}"
        )
    if "reason" not in r.final_json:
        return False, "missing reason field"
    return True, "ok"


def check_t3(r: AgentResult) -> tuple[bool, str]:
    if not _called(r, "get_session_count"):
        return False, "expected to call get_session_count first"
    if not _called_with(
        r, "get_session_info", lambda args: args.get("session_index") == 1
    ):
        return False, "expected get_session_info with session_index=1 (last session)"
    return True, "ok"


def check_t4(r: AgentResult) -> tuple[bool, str]:
    if _called(r, "echo"):
        return False, "should NOT call echo tool (debug-only)"
    useful = {
        "get_session_count",
        "get_session_info",
        "get_frame_at",
        "search_knowledge",
    }
    any_useful = any(
        ex.call.name in useful
        for ev in r.trace.events
        for ex in ev.tool_executions
    )
    if not any_useful:
        return False, "expected to call at least one diagnostic tool"
    return True, "ok"


def check_t5(r: AgentResult) -> tuple[bool, str]:
    if not _called(r, "get_frame_at"):
        return False, "expected to call get_frame_at"
    if not _called(r, "search_knowledge"):
        return False, "expected to call search_knowledge"
    if not isinstance(r.final_json, dict):
        return False, "final output is not a dict"
    if r.final_json.get("verdict") != "FAIL":
        return False, f"expected verdict=FAIL, got {r.final_json.get('verdict')!r}"
    if r.final_json.get("cause_code") != 20:
        return False, f"expected cause_code=20, got {r.final_json.get('cause_code')!r}"
    explanation = (r.final_json.get("explanation") or "").lower()
    if "mac" not in explanation:
        return False, (
            "explanation not grounded in search_knowledge result (missing 'MAC'): "
            f"{explanation[:180]}"
        )
    return True, "ok"


TASKS: list[SmokeTask] = [
    SmokeTask(
        name="T1_single_tool_call",
        description="Single tool call with no arguments",
        system_prompt=(
            "You are a pcap analysis assistant. Use tools to answer questions. "
            "Only call tools that help answer the user's question. "
            "When done, give a short final answer."
        ),
        user_prompt="How many UE sessions are in this capture?",
        check=check_t1,
    ),
    SmokeTask(
        name="T2_structured_output",
        description="Return structured JSON per schema",
        system_prompt=(
            "You are a pcap analyzer. Use tools to investigate, then output the "
            "final structured verdict as a plain JSON object in your assistant "
            "message content. Do NOT call any tool to emit the final JSON — "
            "write it directly as your answer."
        ),
        user_prompt=(
            "Check session at index 0 and tell me if registration succeeded or "
            "failed. Output JSON with fields: verdict (OK/FAIL/INCONCLUSIVE), "
            "reason (string)."
        ),
        check=check_t2,
        response_schema={
            "type": "object",
            "properties": {
                "verdict": {"type": "string", "enum": ["OK", "FAIL", "INCONCLUSIVE"]},
                "reason": {"type": "string"},
            },
            "required": ["verdict", "reason"],
        },
    ),
    SmokeTask(
        name="T3_multi_round",
        description="Multi-round tool calling with dependency",
        system_prompt=(
            "You are a pcap analyzer. To answer, first check how many sessions "
            "exist, then examine the last one. Call tools one at a time."
        ),
        user_prompt="Examine the last UE session in the capture and summarize what happened.",
        check=check_t3,
    ),
    SmokeTask(
        name="T4_avoid_irrelevant_tool",
        description="Must NOT call tools marked irrelevant",
        system_prompt=(
            "You are a pcap analyzer. Use relevant tools only. "
            "Read tool descriptions carefully before calling."
        ),
        user_prompt="Diagnose session at index 0 and tell me what went wrong.",
        check=check_t4,
    ),
    SmokeTask(
        name="T5_compound",
        description="Compound: frame lookup + knowledge lookup + structured output",
        system_prompt=(
            "You are a 5G Core diagnosis expert. Use tools to investigate, then "
            "output the final structured verdict as a plain JSON object in your "
            "assistant message content. Do NOT call any tool to emit the final "
            "JSON — write it directly as your answer."
        ),
        user_prompt=(
            "Frame 42 contains an authentication failure. Look up the frame, "
            "look up what its cause code means, then output JSON with fields: "
            "verdict (OK/FAIL/INCONCLUSIVE), cause_code (int), explanation (string)."
        ),
        check=check_t5,
        response_schema={
            "type": "object",
            "properties": {
                "verdict": {"type": "string", "enum": ["OK", "FAIL", "INCONCLUSIVE"]},
                "cause_code": {"type": "integer"},
                "explanation": {"type": "string"},
            },
            "required": ["verdict", "cause_code", "explanation"],
        },
    ),
]


# ============================================================
# Runner
# ============================================================


@dataclass
class AttemptOutcome:
    task: str
    attempt: int
    passed: bool
    reason: str
    rounds_used: int
    stop_reason: str
    final_text: str | None
    final_json: dict | None
    error: str | None
    elapsed_s: float
    trace: list[dict[str, Any]] | None = None


def _run_attempt(
    kernel: AgentKernel, task: SmokeTask, max_rounds: int, attempt: int
) -> AttemptOutcome:
    t0 = time.perf_counter()
    result = kernel.run(
        TaskSpec(
            system_prompt=task.system_prompt,
            max_rounds=max_rounds,
            response_schema=task.response_schema,
        ),
        task.user_prompt,
    )
    elapsed = time.perf_counter() - t0

    trace_payload = _trace_to_jsonable(result)

    if result.stop_reason == "intelligence_error":
        return AttemptOutcome(
            task=task.name,
            attempt=attempt,
            passed=False,
            reason=f"intelligence_error: {result.error}",
            rounds_used=result.trace.rounds_used(),
            stop_reason=result.stop_reason,
            final_text=result.final_text,
            final_json=result.final_json,
            error=result.error,
            elapsed_s=elapsed,
            trace=trace_payload,
        )

    if result.stop_reason == "max_rounds":
        return AttemptOutcome(
            task=task.name,
            attempt=attempt,
            passed=False,
            reason=f"exceeded max_rounds={max_rounds} without final answer",
            rounds_used=result.trace.rounds_used(),
            stop_reason=result.stop_reason,
            final_text=None,
            final_json=None,
            error=None,
            elapsed_s=elapsed,
            trace=trace_payload,
        )

    passed, reason = task.check(result)
    return AttemptOutcome(
        task=task.name,
        attempt=attempt,
        passed=passed,
        reason=reason,
        rounds_used=result.trace.rounds_used(),
        stop_reason=result.stop_reason,
        final_text=result.final_text,
        final_json=result.final_json,
        error=result.error,
        elapsed_s=elapsed,
        trace=trace_payload,
    )


def _trace_to_jsonable(result: AgentResult) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ev in result.trace.events:
        out.append(
            {
                "round": ev.round_index,
                "assistant_content": ev.assistant_content,
                "reasoning": ev.reasoning,
                "is_final": ev.is_final,
                "tool_executions": [
                    {
                        "name": ex.call.name,
                        "arguments": ex.call.arguments,
                        "ok": ex.ok,
                        "data": ex.data,
                        "refs": ex.refs,
                        "truncated": ex.truncated,
                        "error": ex.error,
                        "elapsed_s": ex.elapsed_s,
                    }
                    for ex in ev.tool_executions
                ],
            }
        )
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="litellm model id")
    parser.add_argument("--api-base", default=None, help="OpenAI-compatible API base URL")
    parser.add_argument("--max-rounds", type=int, default=5)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument(
        "--output-dir",
        default=".traceweaver/runs",
        help="where to write the JSON run report",
    )
    args = parser.parse_args()

    print("=" * 72)
    print("TraceWeaver M1 smoke (AgentKernel + LLMIntelligence)")
    print("=" * 72)
    print(f"Model:      {args.model}")
    print(f"API base:   {args.api_base or '(litellm default)'}")
    print(f"Max rounds: {args.max_rounds}")
    print(f"Attempts:   {args.attempts} per task")
    print(f"Pass gate:  2/{args.attempts} attempts per task; all 5 tasks must pass")
    print("=" * 72)

    intelligence = LLMIntelligence(model=args.model, api_base=args.api_base)
    registry = build_registry()
    kernel = AgentKernel(intelligence, registry)

    all_outcomes: list[AttemptOutcome] = []
    task_passed: dict[str, bool] = {}

    for task in TASKS:
        print(f"\n[{task.name}] {task.description}")
        pass_count = 0
        per_task: list[AttemptOutcome] = []
        for i in range(1, args.attempts + 1):
            print(f"  Attempt {i}/{args.attempts}...", end=" ", flush=True)
            outcome = _run_attempt(kernel, task, args.max_rounds, i)
            per_task.append(outcome)
            all_outcomes.append(outcome)
            flag = "PASS" if outcome.passed else "FAIL"
            print(
                f"{flag} ({outcome.rounds_used} rounds, {outcome.elapsed_s:.1f}s)  "
                f"- {outcome.reason}"
            )
            if outcome.passed:
                pass_count += 1
        ok = pass_count >= (args.attempts + 1) // 2
        task_passed[task.name] = ok
        print(f"  -> Task {task.name}: {'PASS' if ok else 'FAIL'} ({pass_count}/{args.attempts})")

    n_pass = sum(1 for v in task_passed.values() if v)
    all_green = n_pass == len(TASKS)

    print("\n" + "=" * 72)
    print("Summary")
    print("=" * 72)
    print(f"  Passed tasks: {n_pass}/{len(TASKS)}")
    for t in TASKS:
        mark = "PASS" if task_passed[t.name] else "FAIL"
        print(f"    [{mark}] {t.name}")
    print()
    if all_green:
        print("  M1 baseline VERIFIED through AgentKernel.")
    else:
        print("  M1 baseline did NOT pass the gate.")
    print("=" * 72)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    report_path = out_dir / f"m1_smoke_{stamp}.json"
    report = {
        "model": args.model,
        "api_base": args.api_base,
        "max_rounds": args.max_rounds,
        "attempts": args.attempts,
        "all_passed": all_green,
        "task_passed": task_passed,
        "attempts_detail": [o.__dict__ for o in all_outcomes],
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nReport: {report_path}")
    return 0 if all_green else 1


if __name__ == "__main__":
    raise SystemExit(main())
