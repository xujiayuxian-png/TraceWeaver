"""
AgentKernel: the provider-neutral tool-calling loop.

The kernel is deliberately small. Its contract:

    AgentKernel(intelligence, registry).run(task, user_request, ctx?) -> AgentResult

Each round:
  1. Ask the Intelligence layer what to do.
  2. If it wants to call tools:
       - Validate + dispatch each call through the registry.
       - Append the assistant turn (with tool_calls) and each tool-result
         turn to the conversation.
  3. If it emits a final answer:
       - If `task.response_schema` is set, check the required keys are
         present. On a first mismatch, inject a corrective user turn
         and loop once more (bounded by `task.max_rounds`). On repeated
         mismatch, stop with `schema_retry_exhausted`.
  4. Stop at `task.max_rounds` regardless.

The kernel does NOT know about chat templates, provider quirks, Qwen
vs. Llama, or JSON Schema drafts. Layer 4 normalizes everything before
we see it; this file treats every intelligence as equivalent.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from traceweaver.core.intelligence.base import (
    Intelligence,
    IntelligenceRequest,
    IntelligenceResponse,
)
from traceweaver.core.kernel.trace import (
    AgentResult,
    AgentTrace,
    StopReason,
    ToolExecution,
    TraceEvent,
)
from traceweaver.core.profile.base import Profile
from traceweaver.core.tools.base import ToolContext
from traceweaver.core.tools.registry import ToolRegistry
from traceweaver.core.types import Message, ToolCall


@dataclass(frozen=True)
class TaskSpec:
    """One invocation of the kernel."""

    system_prompt: str
    max_rounds: int = 5
    response_schema: dict[str, Any] | None = None
    forbid_tools: tuple[str, ...] = ()
    """
    Tools declared to the LLM but that the kernel must refuse to
    execute. Useful for tests (e.g. an `echo` distractor). The LLM
    still sees the spec, the kernel just returns an error result if
    it is called, so the LLM learns to avoid it.
    """


@dataclass
class _LoopState:
    messages: list[Message] = field(default_factory=list)
    events: list[TraceEvent] = field(default_factory=list)
    schema_retries: int = 0
    # Canonical (tool_name, args_json) -> round first executed.
    # Used to short-circuit identical repeat calls so a small LLM
    # cannot burn its round budget looping on the same query.
    seen_calls: dict[tuple[str, str], int] = field(default_factory=dict)

    def append_message(self, msg: Message) -> None:
        self.messages.append(msg)

    def append_event(self, ev: TraceEvent) -> None:
        self.events.append(ev)


class AgentKernel:
    """
    Drive an Intelligence + ToolRegistry pair to produce a final answer.

    The kernel is stateless between `run` calls; each run builds its
    own `_LoopState`, so a single kernel instance can safely serve
    many sequential tasks.
    """

    def __init__(
        self,
        intelligence: Intelligence,
        registry: ToolRegistry,
    ) -> None:
        self.intelligence = intelligence
        self.registry = registry

    # ---- main entry point -------------------------------------------------

    def run(
        self,
        task: TaskSpec,
        user_request: str,
        ctx: ToolContext | None = None,
    ) -> AgentResult:
        ctx = ctx or ToolContext()
        state = _LoopState(messages=[Message(role="user", content=user_request)])
        tools_spec = self.registry.specs()

        # Reserve the last two rounds for finalization: strip tools from
        # the request so a weak model cannot keep looping on tool calls
        # when the budget is nearly exhausted. First time we enter the
        # window we also inject a clear user nudge.
        finalize_from = max(1, task.max_rounds - 1)
        finalize_nudged = False

        for round_idx in range(1, task.max_rounds + 1):
            in_finalize_window = round_idx >= finalize_from
            tools_for_round = [] if in_finalize_window else tools_spec
            if in_finalize_window and not finalize_nudged:
                state.append_message(
                    Message(
                        role="user",
                        content=(
                            "You have used most of your tool-call budget. "
                            "Do NOT request any more tools. Return the final "
                            "JSON verdict now, using the evidence already in "
                            "your context."
                        ),
                    )
                )
                finalize_nudged = True

            try:
                resp = self.intelligence.think(
                    IntelligenceRequest(
                        system_prompt=task.system_prompt,
                        messages=list(state.messages),
                        tools=tools_for_round,
                        response_schema=task.response_schema,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - surface any backend failure verbatim
                return self._fail(
                    state, stop_reason="intelligence_error", error=str(exc)
                )

            if resp.kind == "final":
                outcome = self._handle_final(round_idx, resp, task, state)
                if outcome is not None:
                    return outcome
                continue

            self._handle_tool_calls(round_idx, resp, task, state, ctx)

        return AgentResult(
            stop_reason="max_rounds",
            trace=AgentTrace(events=state.events),
        )

    # ---- M2 convenience: drive the loop from a loaded Profile ------------

    def run_with_profile(
        self,
        profile: Profile,
        user_request: str,
        *,
        source_handle: Any | None = None,
        knowledge_store: Any | None = None,
        response_schema: dict[str, Any] | None = None,
        forbid_tools: tuple[str, ...] = (),
        extras: dict[str, Any] | None = None,
    ) -> AgentResult:
        """
        Run the kernel with a system_prompt / max_rounds / response_schema
        sourced from `profile`. Caller supplies the already-ingested
        `source_handle` (the kernel doesn't know how to ingest) and
        optionally a `knowledge_store` (usually built from
        `profile.knowledge` at load time).

        Explicit `response_schema` overrides the one declared in the
        profile (lets tests and smokes swap shapes without editing YAML).
        """
        task = TaskSpec(
            system_prompt=profile.llm.system_prompt,
            max_rounds=profile.llm.max_rounds,
            response_schema=(
                response_schema if response_schema is not None else profile.llm.response_schema
            ),
            forbid_tools=forbid_tools,
        )
        ctx = ToolContext(
            extras=extras or {},
            source_handle=source_handle,
            scope=None,
            profile_name=profile.name,
            knowledge_store=knowledge_store,
        )
        return self.run(task, user_request, ctx)

    # ---- per-round handlers ----------------------------------------------

    def _handle_final(
        self,
        round_idx: int,
        resp: IntelligenceResponse,
        task: TaskSpec,
        state: _LoopState,
    ) -> AgentResult | None:
        """
        Returns an AgentResult to end the run, or None to keep looping
        (schema retry case).
        """
        missing = _schema_missing_keys(task.response_schema, resp.final_json)

        if not missing:
            state.append_event(
                TraceEvent(
                    round_index=round_idx,
                    assistant_content=resp.final_text or "",
                    reasoning=resp.reasoning,
                    is_final=True,
                )
            )
            return AgentResult(
                stop_reason="final",
                final_text=resp.final_text,
                final_json=resp.final_json,
                trace=AgentTrace(events=state.events),
            )

        # Schema mismatch: record the failed attempt, push a corrective
        # user turn, and keep looping (bounded by max_rounds).
        state.append_event(
            TraceEvent(
                round_index=round_idx,
                assistant_content=resp.final_text or "",
                reasoning=resp.reasoning,
                is_final=False,
            )
        )
        state.append_message(
            Message(role="assistant", content=resp.final_text or "")
        )
        state.append_message(
            Message(
                role="user",
                content=(
                    "Your previous answer was missing required fields: "
                    f"{sorted(missing)}. Please retry and output a single JSON "
                    "object with all required fields."
                ),
            )
        )
        state.schema_retries += 1
        if state.schema_retries >= 2:
            return AgentResult(
                stop_reason="schema_retry_exhausted",
                final_text=resp.final_text,
                final_json=resp.final_json,
                trace=AgentTrace(events=state.events),
            )
        return None

    def _handle_tool_calls(
        self,
        round_idx: int,
        resp: IntelligenceResponse,
        task: TaskSpec,
        state: _LoopState,
        ctx: ToolContext,
    ) -> None:
        state.append_message(
            Message(
                role="assistant",
                content=resp.assistant_content or "",
                tool_calls=list(resp.tool_calls),
            )
        )

        executions: list[ToolExecution] = []
        for call in resp.tool_calls:
            dup_round = _seen_key_round(state, call, round_idx)
            if dup_round is not None:
                execution = ToolExecution(
                    call=call,
                    ok=False,
                    error=(
                        f"duplicate_call: tool '{call.name}' was already "
                        f"executed in round {dup_round} with identical "
                        "arguments; its result is already in your context. "
                        "Do NOT call it again — finalize your diagnosis now "
                        "using the evidence you already have."
                    ),
                )
            else:
                execution = self._execute_tool(call, task, ctx)
            executions.append(execution)
            state.append_message(
                Message(
                    role="tool",
                    tool_call_id=call.id,
                    name=call.name,
                    content=_tool_result_to_text(execution),
                )
            )

        state.append_event(
            TraceEvent(
                round_index=round_idx,
                assistant_content="",
                reasoning=resp.reasoning,
                tool_executions=executions,
                is_final=False,
            )
        )

    # ---- tool dispatch ---------------------------------------------------

    def _execute_tool(
        self,
        call: ToolCall,
        task: TaskSpec,
        ctx: ToolContext,
    ) -> ToolExecution:
        if call.name in task.forbid_tools:
            return ToolExecution(
                call=call,
                ok=False,
                error=f"tool '{call.name}' is forbidden in this task",
            )
        if not self.registry.has(call.name):
            return ToolExecution(
                call=call,
                ok=False,
                error=f"unknown tool: {call.name}",
            )
        t0 = time.perf_counter()
        try:
            result = self.registry.invoke(call.name, call.arguments, ctx)
        except Exception as exc:  # noqa: BLE001 - a broken tool shouldn't kill the loop
            return ToolExecution(
                call=call,
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
                elapsed_s=time.perf_counter() - t0,
            )
        return ToolExecution(
            call=call,
            ok=True,
            data=result.data,
            refs=result.refs,
            truncated=result.truncated,
            elapsed_s=time.perf_counter() - t0,
        )

    # ---- helpers ---------------------------------------------------------

    @staticmethod
    def _fail(
        state: _LoopState, stop_reason: StopReason, error: str
    ) -> AgentResult:
        return AgentResult(
            stop_reason=stop_reason,
            trace=AgentTrace(events=state.events),
            error=error,
        )


def _canonical_args(args: dict[str, Any] | None) -> str:
    """Stable JSON for duplicate-call detection."""
    import json as _json

    return _json.dumps(args or {}, ensure_ascii=False, sort_keys=True)


def _seen_key_round(
    state: _LoopState,
    call: ToolCall,
    round_idx: int,
) -> int | None:
    """
    Record the call in `state.seen_calls`. Return the round in which
    this exact (name, args) was FIRST seen if it is a repeat, else None.
    """
    key = (call.name, _canonical_args(call.arguments))
    prior = state.seen_calls.get(key)
    if prior is not None:
        return prior
    state.seen_calls[key] = round_idx
    return None


def _schema_missing_keys(
    schema: dict[str, Any] | None,
    final_json: dict[str, Any] | None,
) -> list[str]:
    """Minimal schema check for M1: required keys must be present."""
    if schema is None:
        return []
    if final_json is None:
        return ["<no-json-produced>"]
    required = schema.get("required", []) or []
    return [k for k in required if k not in final_json]


def _tool_result_to_text(execution: ToolExecution) -> str:
    """Render a ToolExecution as the `content` field of a role='tool' message."""
    import json as _json

    if not execution.ok:
        return _json.dumps({"error": execution.error}, ensure_ascii=False)
    body: dict[str, Any] = dict(execution.data)
    if execution.refs:
        body["refs"] = execution.refs
    if execution.truncated:
        body["truncated"] = True
    return _json.dumps(body, ensure_ascii=False)


__all__ = ["AgentKernel", "TaskSpec"]
