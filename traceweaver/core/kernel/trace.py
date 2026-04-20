"""
Agent trace and final result types.

An `AgentTrace` is a structured log of what the kernel did in one run:
every intelligence round, every tool call, every tool result, plus the
terminal outcome. Downstream layers (Case Memory in M3, CLI pretty-print
in M1) read the trace.

Keeping trace types separate from the kernel keeps the kernel file
small and lets tests build traces directly.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from traceweaver.core.types import ToolCall


StopReason = Literal[
    "final",
    "max_rounds",
    "schema_retry_exhausted",
    "intelligence_error",
    "tool_error",
]


class ToolExecution(BaseModel):
    """A single tool invocation plus its outcome."""

    model_config = ConfigDict(frozen=True)

    call: ToolCall
    ok: bool
    data: dict[str, Any] = Field(default_factory=dict)
    refs: list[str] = Field(default_factory=list)
    truncated: bool = False
    error: str | None = None
    elapsed_s: float = 0.0


class TraceEvent(BaseModel):
    """One round of the kernel loop."""

    model_config = ConfigDict(frozen=True)

    round_index: int
    assistant_content: str = ""
    reasoning: str | None = None
    tool_executions: list[ToolExecution] = Field(default_factory=list)
    is_final: bool = False
    # Telemetry (P1.1)
    tokens_used: int | None = None  # LLM tokens for this round
    cost_usd: float | None = None   # Estimated cost for this round


class AgentTrace(BaseModel):
    """Everything that happened in one `AgentKernel.run` call."""

    model_config = ConfigDict(frozen=True)

    events: list[TraceEvent] = Field(default_factory=list)

    def rounds_used(self) -> int:
        return len(self.events)

    def tool_calls_total(self) -> int:
        return sum(len(e.tool_executions) for e in self.events)

    def called(self, name: str) -> bool:
        for e in self.events:
            for ex in e.tool_executions:
                if ex.call.name == name:
                    return True
        return False

    # Telemetry aggregation (P1.1)
    def total_tokens(self) -> int:
        """Sum tokens across all rounds with telemetry."""
        return sum(
            e.tokens_used for e in self.events if e.tokens_used is not None
        )

    def total_cost_usd(self) -> float:
        """Sum estimated cost across all rounds with telemetry."""
        return sum(
            e.cost_usd for e in self.events if e.cost_usd is not None
        )

    def wall_clock_s(self) -> float:
        """Total tool execution time (not LLM latency)."""
        return sum(
            ex.elapsed_s for e in self.events for ex in e.tool_executions
        )


class AgentResult(BaseModel):
    """What `AgentKernel.run` returns to its caller."""

    model_config = ConfigDict(frozen=True)

    stop_reason: StopReason
    final_text: str | None = None
    final_json: dict[str, Any] | None = None
    trace: AgentTrace = Field(default_factory=AgentTrace)
    error: str | None = None
    # Telemetry summary (P1.1)
    total_tokens: int | None = None
    total_cost_usd: float | None = None
    wall_clock_s: float | None = None

    @property
    def ok(self) -> bool:
        return self.stop_reason == "final"


__all__ = [
    "AgentResult",
    "AgentTrace",
    "StopReason",
    "ToolExecution",
    "TraceEvent",
]
