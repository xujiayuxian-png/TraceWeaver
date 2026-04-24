from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

from traceweaver.core.protocols import ToolCall


@dataclass(frozen=True)
class ToolExecution:
    call: ToolCall
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    refs: list[str] = field(default_factory=list)
    truncated: bool = False
    error: str | None = None


@dataclass(frozen=True)
class TraceEvent:
    round_index: int
    is_final: bool
    tool_executions: list[ToolExecution] = field(default_factory=list)
    assistant_content: str = ""
    reasoning: str | None = None


@dataclass(frozen=True)
class AgentTrace:
    events: list[TraceEvent] = field(default_factory=list)
    wall_clock_s: float = 0.0

    def total_tokens(self) -> int:
        return 0

    def total_cost_usd(self) -> float:
        return 0.0

    def tool_time_s(self) -> float:
        # Tool execution time is not tracked individually in this implementation
        # Return 0.0 as a placeholder
        return 0.0


@dataclass(frozen=True)
class AgentResult:
    stop_reason: str
    final_text: str | None = None
    final_json: dict[str, Any] | None = None
    trace: AgentTrace = field(default_factory=AgentTrace)
    error: str | None = None
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    wall_clock_s: float = 0.0
