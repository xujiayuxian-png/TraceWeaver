"""
Integration tests for AgentKernel.

No network, no litellm: we plug a scripted `ScriptedIntelligence` and
trivial pure-function tools into the kernel and assert on the trace +
final result for each interesting shape of conversation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from traceweaver.core.intelligence.base import (
    Intelligence,
    IntelligenceRequest,
    IntelligenceResponse,
)
from traceweaver.core.kernel import AgentKernel, TaskSpec
from traceweaver.core.tools.base import Tool, ToolContext, ToolResult, ToolSpec
from traceweaver.core.tools.registry import ToolRegistry
from traceweaver.core.types import ToolCall


# ---- scripted intelligence ------------------------------------------------


@dataclass
class ScriptedIntelligence(Intelligence):
    """
    Replay a fixed queue of IntelligenceResponse objects, one per
    `think` call. Records every request it was asked to handle so tests
    can assert on conversation shape.
    """

    name: str = "scripted"
    queue: list[IntelligenceResponse] = field(default_factory=list)
    calls: list[IntelligenceRequest] = field(default_factory=list)
    raise_on_call: Exception | None = None

    def think(self, request: IntelligenceRequest) -> IntelligenceResponse:  # type: ignore[override]
        self.calls.append(request)
        if self.raise_on_call is not None:
            raise self.raise_on_call
        if not self.queue:
            raise AssertionError("ScriptedIntelligence ran out of responses")
        return self.queue.pop(0)


# ---- toy tools ------------------------------------------------------------


class EchoTool(Tool):
    spec = ToolSpec(
        name="echo",
        description="Echo input text.",
        parameters_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    )

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:  # type: ignore[override]
        self.calls.append(kwargs)
        return ToolResult(data={"echoed": kwargs.get("text", "")})


class AddTool(Tool):
    spec = ToolSpec(
        name="add",
        description="Return a + b.",
        parameters_schema={
            "type": "object",
            "properties": {
                "a": {"type": "integer"},
                "b": {"type": "integer"},
            },
            "required": ["a", "b"],
        },
    )

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:  # type: ignore[override]
        a, b = kwargs["a"], kwargs["b"]
        return ToolResult(data={"sum": a + b})


class BoomTool(Tool):
    spec = ToolSpec(
        name="boom",
        description="Always raises.",
        parameters_schema={"type": "object", "properties": {}},
    )

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:  # type: ignore[override]
        raise RuntimeError("kaboom")


def _registry(*tools: Tool) -> ToolRegistry:
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)
    return reg


def _final(text: str = "", as_json: dict | None = None) -> IntelligenceResponse:
    return IntelligenceResponse(
        kind="final", final_text=text, final_json=as_json
    )


def _tool_call(name: str, **args) -> IntelligenceResponse:
    return IntelligenceResponse(
        kind="tool_calls",
        tool_calls=[ToolCall(id=f"call-{name}", name=name, arguments=args)],
    )


# ---- tests ----------------------------------------------------------------


def test_immediate_final_no_tool_calls():
    intel = ScriptedIntelligence(queue=[_final(text="Hello.")])
    kernel = AgentKernel(intel, _registry(EchoTool()))

    result = kernel.run(TaskSpec(system_prompt="sys"), "say hi")

    assert result.ok
    assert result.final_text == "Hello."
    assert result.trace.rounds_used() == 1
    assert result.trace.tool_calls_total() == 0
    assert len(intel.calls) == 1
    assert intel.calls[0].messages[0].role == "user"
    assert intel.calls[0].messages[0].content == "say hi"


def test_single_tool_then_final():
    add = AddTool()
    intel = ScriptedIntelligence(
        queue=[
            _tool_call("add", a=2, b=3),
            _final(text="The sum is 5."),
        ]
    )
    kernel = AgentKernel(intel, _registry(add))

    result = kernel.run(TaskSpec(system_prompt="sys"), "add 2 and 3")

    assert result.ok
    assert result.trace.rounds_used() == 2
    assert result.trace.tool_calls_total() == 1
    assert result.trace.events[0].tool_executions[0].data == {"sum": 5}
    assert result.trace.called("add")

    second_req = intel.calls[1]
    msgs = second_req.messages
    assert msgs[-2].role == "assistant" and msgs[-2].tool_calls
    assert msgs[-1].role == "tool"
    assert '"sum": 5' in msgs[-1].content


def test_multi_round_dependent_calls():
    intel = ScriptedIntelligence(
        queue=[
            _tool_call("add", a=1, b=2),
            _tool_call("add", a=3, b=4),
            _final(text="done", as_json={"results": [3, 7]}),
        ]
    )
    kernel = AgentKernel(intel, _registry(AddTool()))

    result = kernel.run(TaskSpec(system_prompt="sys"), "add twice")

    assert result.ok
    assert result.trace.rounds_used() == 3
    assert result.trace.tool_calls_total() == 2


def test_max_rounds_exceeded():
    intel = ScriptedIntelligence(
        queue=[_tool_call("add", a=1, b=1) for _ in range(10)]
    )
    kernel = AgentKernel(intel, _registry(AddTool()))

    result = kernel.run(
        TaskSpec(system_prompt="sys", max_rounds=3), "loop forever"
    )

    assert result.stop_reason == "max_rounds"
    assert result.trace.rounds_used() == 3
    assert result.final_text is None


def test_schema_retry_then_success():
    schema = {
        "type": "object",
        "properties": {
            "verdict": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": ["verdict", "reason"],
    }
    intel = ScriptedIntelligence(
        queue=[
            _final(text='{"verdict": "FAIL"}', as_json={"verdict": "FAIL"}),
            _final(
                text='{"verdict": "FAIL", "reason": "auth"}',
                as_json={"verdict": "FAIL", "reason": "auth"},
            ),
        ]
    )
    kernel = AgentKernel(intel, _registry(AddTool()))

    result = kernel.run(
        TaskSpec(system_prompt="sys", response_schema=schema),
        "diagnose",
    )

    assert result.ok
    assert result.final_json == {"verdict": "FAIL", "reason": "auth"}
    assert result.trace.rounds_used() == 2
    corrective_user = intel.calls[1].messages[-1]
    assert corrective_user.role == "user"
    assert "missing required fields" in corrective_user.content


def test_schema_retry_exhausted():
    schema = {"type": "object", "required": ["verdict"]}
    intel = ScriptedIntelligence(
        queue=[
            _final(text="nope 1", as_json=None),
            _final(text="nope 2", as_json=None),
        ]
    )
    kernel = AgentKernel(intel, _registry(AddTool()))

    result = kernel.run(
        TaskSpec(system_prompt="sys", response_schema=schema),
        "diagnose",
    )

    assert result.stop_reason == "schema_retry_exhausted"
    assert not result.ok


def test_forbidden_tool_returns_error_but_loop_continues():
    intel = ScriptedIntelligence(
        queue=[
            _tool_call("echo", text="please let me through"),
            _final(text="fine, giving up on echo"),
        ]
    )
    echo = EchoTool()
    kernel = AgentKernel(intel, _registry(echo, AddTool()))

    result = kernel.run(
        TaskSpec(system_prompt="sys", forbid_tools=("echo",)),
        "try to use echo",
    )

    assert result.ok
    exec0 = result.trace.events[0].tool_executions[0]
    assert exec0.ok is False
    assert "forbidden" in (exec0.error or "")
    assert echo.calls == []


def test_unknown_tool_reported_but_not_fatal():
    intel = ScriptedIntelligence(
        queue=[
            _tool_call("ghost"),
            _final(text="sorry, tried unknown"),
        ]
    )
    kernel = AgentKernel(intel, _registry(AddTool()))

    result = kernel.run(TaskSpec(system_prompt="sys"), "...")

    assert result.ok
    exec0 = result.trace.events[0].tool_executions[0]
    assert exec0.ok is False
    assert "unknown tool" in (exec0.error or "")


def test_tool_raising_exception_does_not_kill_loop():
    intel = ScriptedIntelligence(
        queue=[
            _tool_call("boom"),
            _final(text="oh well"),
        ]
    )
    kernel = AgentKernel(intel, _registry(BoomTool()))

    result = kernel.run(TaskSpec(system_prompt="sys"), "...")

    assert result.ok
    exec0 = result.trace.events[0].tool_executions[0]
    assert exec0.ok is False
    assert "RuntimeError" in (exec0.error or "")
    assert "kaboom" in (exec0.error or "")


def test_intelligence_exception_stops_with_error():
    intel = ScriptedIntelligence(raise_on_call=RuntimeError("llm down"))
    kernel = AgentKernel(intel, _registry(AddTool()))

    result = kernel.run(TaskSpec(system_prompt="sys"), "...")

    assert result.stop_reason == "intelligence_error"
    assert result.error is not None and "llm down" in result.error
    assert result.trace.rounds_used() == 0


def test_forbidden_data_key_rejected_by_registry():
    """
    A tool cannot smuggle 'verdict' etc. through its ToolResult; the
    registry enforces the contract before the kernel ever sees the
    result.
    """

    class CheaterTool(Tool):
        spec = ToolSpec(
            name="cheat",
            description="smuggles judgement",
            parameters_schema={"type": "object", "properties": {}},
        )

        def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:  # type: ignore[override]
            return ToolResult(data={"verdict": "FAIL", "x": 1})

    intel = ScriptedIntelligence(queue=[_tool_call("cheat"), _final(text="k")])
    kernel = AgentKernel(intel, _registry(CheaterTool()))

    result = kernel.run(TaskSpec(system_prompt="sys"), "...")

    # The tool execution fails (registry raised), the kernel wraps it
    # as an error result and carries on to the next round.
    assert result.ok
    exec0 = result.trace.events[0].tool_executions[0]
    assert exec0.ok is False
    assert "forbidden data keys" in (exec0.error or "")


def test_openai_tool_spec_rendered_correctly():
    reg = _registry(EchoTool(), AddTool())
    specs = reg.specs()
    assert {s["function"]["name"] for s in specs} == {"echo", "add"}
    for s in specs:
        assert s["type"] == "function"
        assert "parameters" in s["function"]


def test_registry_invoke_coerces_string_integers():
    """LLMs often pass numeric args as strings; the registry coerces."""
    reg = _registry(AddTool())
    result = reg.invoke("add", {"a": "2", "b": "3"}, ToolContext())
    assert result.data == {"sum": 5}


def test_registry_missing_required_arg_raises():
    reg = _registry(AddTool())
    with pytest.raises(ValueError, match="missing required args"):
        reg.invoke("add", {"a": 1}, ToolContext())
