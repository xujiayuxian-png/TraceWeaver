from __future__ import annotations
import json
import time
from dataclasses import dataclass, field
from typing import Any

from traceweaver.core.protocols import (
    Intelligence,
    IntelligenceRequest,
    IntelligenceResponse,
    Message,
    Tool,
    ToolCall,
    ToolContext,
)
from traceweaver.core.loop_engine import LoopEngine, LoopState
from traceweaver.core.schema_guard import SchemaGuard
from traceweaver.core.tool_dispatcher import ToolDispatcher
from traceweaver.core.trace import AgentResult, AgentTrace, TraceEvent, ToolExecution


@dataclass(frozen=True)
class TaskSpec:
    system_prompt: str
    max_rounds: int = 5
    response_schema: dict[str, Any] | None = None
    forbid_tools: tuple[str, ...] = ()


class AgentKernel:
    def __init__(
        self,
        intelligence: Intelligence,
        tools: list[Tool],
    ):
        self.intelligence = intelligence
        self.dispatcher = ToolDispatcher(tools)
        self.loop_engine = LoopEngine()
        self.schema_guard = SchemaGuard()

    def run(
        self,
        task: TaskSpec,
        user_request: str,
        ctx: ToolContext | None = None,
    ) -> AgentResult:
        ctx = ctx or ToolContext()
        state = self.loop_engine.create_state(task, user_request)
        tools_spec = [t.spec.to_openai_tool() for t in self.dispatcher.tool_list]

        for round_idx in range(1, task.max_rounds + 1):
            # Budget warning
            tools_for_round = tools_spec if round_idx < task.max_rounds - 1 else []
            if round_idx >= task.max_rounds - 1:
                state.append_message(
                    Message(
                        role="user",
                        content="Budget nearly exhausted. Return final JSON now.",
                    )
                )

            # Call LLM
            try:
                resp = self.intelligence.think(
                    IntelligenceRequest(
                        system_prompt=task.system_prompt,
                        messages=list(state.messages),
                        tools=tools_for_round or None,
                        response_schema=task.response_schema,
                    )
                )
                state.responses.append(resp)
            except Exception as exc:
                return self._finalize(state, "intelligence_error", error=str(exc))

            # Handle response
            if resp.kind == "final":
                result = self._handle_final(round_idx, resp, task, state)
                if result:
                    return result
                continue

            self._handle_tool_calls(round_idx, resp, state, ctx, task)

        return self._finalize(state, "max_rounds")

    def _handle_final(
        self,
        round_idx: int,
        resp: IntelligenceResponse,
        task: TaskSpec,
        state: LoopState,
    ) -> AgentResult | None:
        if not task.response_schema:
            state.append_event(
                TraceEvent(
                    round_index=round_idx,
                    is_final=True,
                    assistant_content=resp.final_text or "",
                )
            )
            return self._finalize(state, "final", resp=resp)

        valid, error_msg = self.schema_guard.check(
            resp.final_json, task.response_schema
        )
        if valid:
            state.append_event(
                TraceEvent(
                    round_index=round_idx,
                    is_final=True,
                    assistant_content=resp.final_text or "",
                )
            )
            return self._finalize(state, "final", resp=resp)

        # Schema retry
        state.append_event(
            TraceEvent(
                round_index=round_idx,
                assistant_content=resp.final_text or "",
                is_final=False,
            )
        )
        state.append_message(
            Message(role="assistant", content=resp.final_text or "")
        )
        state.append_message(
            Message(
                role="user",
                content=f"Schema validation failed: {error_msg}. Retry with correct JSON.",
            )
        )
        state.schema_retries += 1

        if state.schema_retries >= 2:
            return self._finalize(state, "schema_retry_exhausted", resp=resp)
        return None

    def _handle_tool_calls(
        self,
        round_idx: int,
        resp: IntelligenceResponse,
        state: LoopState,
        ctx: ToolContext,
        task: TaskSpec,
    ) -> None:
        state.append_message(
            Message(
                role="assistant",
                content=resp.assistant_content or "",
                tool_calls=[
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in resp.tool_calls
                ],
            )
        )

        executions = self.dispatcher.dispatch(
            resp.tool_calls, ctx, task.forbid_tools, state.seen_calls
        )

        for ex in executions:
            content = self._render_execution(ex)
            state.append_message(
                Message(
                    role="tool",
                    tool_call_id=ex.call.id,
                    name=ex.call.name,
                    content=content,
                )
            )

        state.append_event(
            TraceEvent(
                round_index=round_idx,
                tool_executions=executions,
                is_final=False,
                reasoning=resp.reasoning,
            )
        )

    def _render_execution(self, ex: ToolExecution) -> str:
        if not ex.ok:
            return json.dumps({"error": ex.error}, ensure_ascii=False)
        body = dict(ex.data)
        if ex.refs:
            body["refs"] = ex.refs
        if ex.truncated:
            body["truncated"] = True
        return json.dumps(body, ensure_ascii=False)

    def _finalize(
        self,
        state: LoopState,
        stop_reason: str,
        resp: IntelligenceResponse | None = None,
        error: str | None = None,
    ) -> AgentResult:
        wall_clock = time.perf_counter() - state.t0
        trace = AgentTrace(events=state.events, wall_clock_s=wall_clock)
        # Aggregate tokens/cost from all responses if available
        total_tokens = sum(
            (r.total_tokens or 0) for r in state.responses if r.total_tokens
        )
        total_cost = sum(
            (r.total_cost_usd or 0) for r in state.responses if r.total_cost_usd
        )
        return AgentResult(
            stop_reason=stop_reason,
            final_text=resp.final_text if resp else None,
            final_json=resp.final_json if resp else None,
            trace=trace,
            error=error,
            total_tokens=total_tokens,
            total_cost_usd=total_cost,
            wall_clock_s=wall_clock,
        )

    def run_with_profile(
        self,
        profile,
        user_request: str,
        source_handle=None,
        knowledge_store=None,
        response_schema=None,
    ):
        """Run kernel with a profile configuration."""
        from traceweaver.core.protocols import ToolContext

        llm = profile.llm
        schema = response_schema or llm.response_schema

        task = TaskSpec(
            system_prompt=llm.system_prompt,
            max_rounds=llm.max_rounds,
            response_schema=schema,
        )
        ctx = ToolContext(source_handle=source_handle, knowledge_store=knowledge_store)
        return self.run(task, user_request, ctx)
