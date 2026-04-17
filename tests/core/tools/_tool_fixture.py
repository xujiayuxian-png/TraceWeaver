"""Test fixtures for tool loader tests."""

from __future__ import annotations

from typing import Any

from traceweaver.core.tools.base import Tool, ToolContext, ToolResult, ToolSpec


class StubTool(Tool):
    def __init__(self, name: str = "stub", payload: str = "ok") -> None:
        self.spec = ToolSpec(name=name, description="stub")
        self._payload = payload

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        return ToolResult(data={"payload": self._payload})


class NotATool:
    pass


def make_stub(name: str = "made") -> StubTool:
    return StubTool(name=name, payload="factory")


def broken_factory() -> str:
    return "not a tool"
