"""
P1.1 telemetry tests: verify that tokens / cost / wall-clock are
recorded on EVERY exit path, and that _extract_usage handles both
dict-style and object-style usage payloads from litellm.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from traceweaver.core.protocols import (
    Intelligence,
    IntelligenceRequest,
    IntelligenceResponse,
    Tool,
    ToolCall,
    ToolContext,
    ToolResult,
    ToolSpec,
)
from traceweaver.core.intelligence.litellm_adapter import (
    _extract_usage,
    _get_usage_field,
)
from traceweaver.core.kernel import AgentKernel, TaskSpec
from traceweaver.core.tools.registry import ToolRegistry


# ---- _extract_usage unit tests -------------------------------------


def test_extract_usage_from_object_style():
    """litellm OpenAI provider returns usage as Pydantic-like object."""
    usage = SimpleNamespace(prompt_tokens=100, completion_tokens=50, total_tokens=150)
    resp = SimpleNamespace(usage=usage)
    tokens, cost = _extract_usage(resp, "openai/gpt-4")
    assert tokens == 150
    assert cost is not None and cost >= 0  # >0 when litellm knows the model, 0.0 fallback otherwise


def test_extract_usage_from_dict_style():
    """Some providers return usage as plain dict."""
    resp = SimpleNamespace(usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150})
    tokens, cost = _extract_usage(resp, "openai/gpt-4")
    assert tokens == 150
    assert cost is not None and cost >= 0  # >0 when litellm knows the model, 0.0 fallback otherwise


def test_extract_usage_missing_returns_none():
    """No usage field => (None, None)."""
    resp = SimpleNamespace(usage=None)
    assert _extract_usage(resp, "any") == (None, None)

    resp_no_attr = SimpleNamespace()
    assert _extract_usage(resp_no_attr, "any") == (None, None)


def test_extract_usage_computes_total_from_parts():
    """If total_tokens missing but prompt+completion exist, sum them."""
    usage = SimpleNamespace(prompt_tokens=80, completion_tokens=20, total_tokens=0)
    resp = SimpleNamespace(usage=usage)
    tokens, _ = _extract_usage(resp, "local")
    assert tokens == 100


def test_extract_usage_local_model_zero_cost():
    """Local/unknown models => cost 0 but tokens reported."""
    usage = SimpleNamespace(prompt_tokens=100, completion_tokens=50, total_tokens=150)
    resp = SimpleNamespace(usage=usage)
    tokens, cost = _extract_usage(resp, "openai/qwen3.5-9b")
    assert tokens == 150
    assert cost == 0.0


def test_get_usage_field_handles_none():
    assert _get_usage_field(None, "prompt_tokens") == 0


def test_get_usage_field_handles_garbage():
    """Non-numeric values should coerce safely to 0."""
    usage = SimpleNamespace(prompt_tokens="not_a_number")
    assert _get_usage_field(usage, "prompt_tokens") == 0


# ---- kernel integration tests: summary on every exit path ----------


@dataclass
class ScriptedIntelligence(Intelligence):
    name: str = "scripted"
    queue: list[IntelligenceResponse] = field(default_factory=list)
    raise_on_call: Exception | None = None

    def think(self, request: IntelligenceRequest) -> IntelligenceResponse:  # type: ignore[override]
        if self.raise_on_call is not None:
            raise self.raise_on_call
        if not self.queue:
            raise AssertionError("scripted queue empty")
        return self.queue.pop(0)


class NoopTool(Tool):
    spec = ToolSpec(
        name="noop",
        description="No-op.",
        parameters_schema={"type": "object", "properties": {}},
    )

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:  # type: ignore[override]
        return ToolResult(data={"ok": True})


def _make_kernel(queue: list[IntelligenceResponse], raise_on_call: Exception | None = None) -> AgentKernel:
    intel = ScriptedIntelligence(queue=queue, raise_on_call=raise_on_call)
    return AgentKernel(intel, [NoopTool()])


SCHEMA = {"type": "object", "required": ["verdict"], "properties": {"verdict": {"type": "string"}}}


def test_final_path_populates_summary():
    """Happy path: summary fields populated with correct values."""
    kernel = _make_kernel([
        IntelligenceResponse(
            kind="final",
            final_text='{"verdict": "ok"}',
            final_json={"verdict": "ok"},
            total_tokens=150,
            total_cost_usd=0.003,
        ),
    ])
    task = TaskSpec(system_prompt="", max_rounds=5, response_schema=SCHEMA)
    result = kernel.run(task, "test")

    assert result.stop_reason == "final"
    assert result.total_tokens == 150
    assert result.total_cost_usd == pytest.approx(0.003)
    assert result.wall_clock_s is not None and result.wall_clock_s >= 0
    assert result.trace.wall_clock_s >= 0


def test_max_rounds_path_populates_summary():
    """Even when budget runs out, summary must be present."""
    # Every round returns a tool call so we never finalize.
    tool_resp = IntelligenceResponse(
        kind="tool_calls",
        tool_calls=[ToolCall(id="c1", name="noop", arguments={})],
        total_tokens=50,
        total_cost_usd=0.001,
    )
    # Need distinct call IDs to avoid duplicate-call short-circuit
    queue = [
        IntelligenceResponse(
            kind="tool_calls",
            tool_calls=[ToolCall(id=f"c{i}", name="noop", arguments={"x": i})],
            total_tokens=50,
            total_cost_usd=0.001,
        )
        for i in range(10)
    ]
    kernel = _make_kernel(queue)
    task = TaskSpec(system_prompt="", max_rounds=3, response_schema=SCHEMA)
    result = kernel.run(task, "test")

    assert result.stop_reason == "max_rounds"
    # 3 rounds * 50 tokens each
    assert result.total_tokens == 150
    assert result.total_cost_usd == pytest.approx(0.003)
    assert result.wall_clock_s is not None


def test_intelligence_error_populates_summary():
    """Exception from intelligence => still get wall_clock."""
    kernel = _make_kernel([], raise_on_call=RuntimeError("boom"))
    task = TaskSpec(system_prompt="", max_rounds=5, response_schema=SCHEMA)
    result = kernel.run(task, "test")

    assert result.stop_reason == "intelligence_error"
    assert result.error == "boom"
    # No rounds executed so tokens/cost None, but wall_clock still set
    assert result.total_tokens == 0
    assert result.total_cost_usd == 0.0
    assert result.wall_clock_s is not None and result.wall_clock_s >= 0


def test_schema_retry_exhausted_populates_summary():
    """Schema-retry exhaustion exit path also fills summary."""
    bad_response = IntelligenceResponse(
        kind="final",
        final_text='{"wrong": "field"}',
        final_json={"wrong": "field"},  # missing required "verdict"
        total_tokens=100,
        total_cost_usd=0.002,
    )
    kernel = _make_kernel([bad_response, bad_response])
    task = TaskSpec(system_prompt="", max_rounds=5, response_schema=SCHEMA)
    result = kernel.run(task, "test")

    assert result.stop_reason == "schema_retry_exhausted"
    # 2 failed attempts * 100 tokens
    assert result.total_tokens == 200
    assert result.total_cost_usd == pytest.approx(0.004)
    assert result.wall_clock_s is not None


def test_wall_clock_greater_than_tool_time():
    """wall_clock_s covers the whole run (LLM + tool + overhead), not just tools."""
    kernel = _make_kernel([
        IntelligenceResponse(
            kind="final",
            final_text='{"verdict": "ok"}',
            final_json={"verdict": "ok"},
            tokens_used=50,
        ),
    ])
    task = TaskSpec(system_prompt="", max_rounds=5, response_schema=SCHEMA)
    result = kernel.run(task, "test")

    # No tool calls were made, so tool_time_s == 0 but wall_clock_s > 0
    with pytest.warns(DeprecationWarning, match="tool_time_s"):
        assert result.trace.tool_time_s() == 0.0
    assert result.wall_clock_s > 0


def test_no_telemetry_means_none_summary():
    """If intelligence doesn't report usage, summary token/cost remain None."""
    kernel = _make_kernel([
        IntelligenceResponse(
            kind="final",
            final_text='{"verdict": "ok"}',
            final_json={"verdict": "ok"},
            # no tokens_used / cost_usd
        ),
    ])
    task = TaskSpec(system_prompt="", max_rounds=5, response_schema=SCHEMA)
    result = kernel.run(task, "test")

    assert result.stop_reason == "final"
    assert result.total_tokens == 0
    assert result.total_cost_usd == 0.0
    # But wall_clock is still measured
    assert result.wall_clock_s is not None
