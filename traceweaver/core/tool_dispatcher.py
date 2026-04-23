import json
from typing import Any

from traceweaver.core.protocols import Tool, ToolCall, ToolContext
from traceweaver.core.trace import ToolExecution


class ToolDispatcher:
    def __init__(self, tools: list[Tool]):
        self.tools = {t.spec.name: t for t in tools}
        self.tool_list = tools

    def dispatch(
        self,
        calls: list[ToolCall],
        ctx: ToolContext,
        forbid: tuple[str, ...],
        seen: dict[tuple[str, str], int],
    ) -> list[ToolExecution]:
        executions: list[ToolExecution] = []

        for call in calls:
            if call.name in forbid:
                executions.append(
                    ToolExecution(call=call, ok=False, error=f"tool '{call.name}' is forbidden")
                )
                continue

            if call.name not in self.tools:
                executions.append(
                    ToolExecution(call=call, ok=False, error=f"unknown tool: {call.name}")
                )
                continue

            # Duplicate detection
            key = (call.name, json.dumps(call.arguments, ensure_ascii=False, sort_keys=True))
            if key in seen:
                executions.append(
                    ToolExecution(
                        call=call,
                        ok=False,
                        error=f"duplicate_call: already executed in round {seen[key]}",
                    )
                )
                continue

            seen[key] = len(executions)

            tool = self.tools[call.name]
            try:
                result = tool.run(ctx, **call.arguments)
                executions.append(
                    ToolExecution(
                        call=call,
                        ok=True,
                        data=result.data,
                        refs=result.refs,
                        truncated=result.truncated,
                    )
                )
            except Exception as exc:
                executions.append(
                    ToolExecution(
                        call=call, ok=False, error=f"{type(exc).__name__}: {exc}"
                    )
                )

        return executions
