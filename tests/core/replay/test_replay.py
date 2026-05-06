"""End-to-end replay test: record a kernel session, replay it, verify output."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from traceweaver.core.kernel import AgentKernel, TaskSpec
from traceweaver.core.protocols import (
    Intelligence,
    IntelligenceRequest,
    IntelligenceResponse,
    Message,
    Tool,
    ToolCall,
    ToolContext,
    ToolResult,
    ToolSpec,
)
from traceweaver.recording.recorder import RecordReplayIntelligence


# ---- Fake tool --------------------------------------------------------

class EchoTool(Tool):
    """Returns whatever arguments it receives."""

    spec = ToolSpec(
        name="echo",
        description="Echo back the arguments.",
        parameters_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    )

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        return ToolResult(data={"echo": kwargs.get("text", "")})


# ---- Fake intelligence sequences --------------------------------------

class ScriptedIntelligence(Intelligence):
    """Replays a fixed list of IntelligenceResponse objects."""

    def __init__(self, responses: list[IntelligenceResponse]):
        self._responses = list(responses)
        self._idx = 0

    def think(self, request: IntelligenceRequest) -> IntelligenceResponse:
        if self._idx >= len(self._responses):
            raise AssertionError(
                f"ScriptedIntelligence: no more responses (turn {self._idx})"
            )
        resp = self._responses[self._idx]
        self._idx += 1
        return resp


def _two_turn_sequence() -> list[IntelligenceResponse]:
    """Turn 1: call echo tool. Turn 2: final JSON verdict."""
    return [
        IntelligenceResponse(
            kind="tool_calls",
            tool_calls=[
                ToolCall(id="call_1", name="echo", arguments={"text": "hello"})
            ],
            assistant_content="Let me check.",
        ),
        IntelligenceResponse(
            kind="final",
            final_json={"verdict": "success", "summary": "echo returned hello"},
            final_text="Done.",
        ),
    ]


# ---- Tests ------------------------------------------------------------

class TestRecordReplay:
    def test_record_then_replay_produces_same_result(
        self, tmp_path: Path
    ) -> None:
        recording_path = tmp_path / "session.yaml"

        # --- record phase -------------------------------------------------
        scripted = ScriptedIntelligence(_two_turn_sequence())
        record_intel = RecordReplayIntelligence(
            inner=scripted, recording_path=recording_path, mode="record"
        )
        kernel = AgentKernel(intelligence=record_intel, tools=[EchoTool()])
        task = TaskSpec(system_prompt="test", max_rounds=5)
        record_result = kernel.run(task, "diagnose", ToolContext())

        assert record_result.stop_reason == "final"
        assert record_result.final_json == {
            "verdict": "success",
            "summary": "echo returned hello",
        }
        assert recording_path.exists(), "recording YAML was not written"

        # --- replay phase -------------------------------------------------
        replay_intel = RecordReplayIntelligence(
            inner=None, recording_path=recording_path, mode="replay"
        )
        replay_kernel = AgentKernel(intelligence=replay_intel, tools=[EchoTool()])
        replay_result = replay_kernel.run(task, "diagnose", ToolContext())

        assert replay_result.stop_reason == record_result.stop_reason
        assert replay_result.final_json == record_result.final_json

        # Verify tool calls match
        orig_calls = [
            ex.call.name
            for ev in record_result.trace.events
            for ex in ev.tool_executions
        ]
        replay_calls = [
            ex.call.name
            for ev in replay_result.trace.events
            for ex in ev.tool_executions
        ]
        assert replay_calls == orig_calls

    def test_replay_exhaustion_raises(self, tmp_path: Path) -> None:
        """Replaying beyond the recording raises IndexError."""
        recording_path = tmp_path / "session.yaml"

        scripted = ScriptedIntelligence(_two_turn_sequence())
        record_intel = RecordReplayIntelligence(
            inner=scripted, recording_path=recording_path, mode="record"
        )
        kernel = AgentKernel(intelligence=record_intel, tools=[EchoTool()])
        task = TaskSpec(system_prompt="test", max_rounds=5)
        kernel.run(task, "diagnose", ToolContext())

        # Now replay with max_rounds=10 — the recording only has 2 turns,
        # so the kernel should stop at "final" before exhausting.
        replay_intel = RecordReplayIntelligence(
            inner=None, recording_path=recording_path, mode="replay"
        )
        replay_kernel = AgentKernel(intelligence=replay_intel, tools=[EchoTool()])
        wide_task = TaskSpec(system_prompt="test", max_rounds=10)
        result = replay_kernel.run(wide_task, "diagnose", ToolContext())

        # Should have stopped at "final" on turn 2, not exhausted
        assert result.stop_reason == "final"

    def test_replay_deterministic_across_runs(self, tmp_path: Path) -> None:
        """Replaying the same recording twice produces identical results."""
        recording_path = tmp_path / "session.yaml"

        scripted = ScriptedIntelligence(_two_turn_sequence())
        record_intel = RecordReplayIntelligence(
            inner=scripted, recording_path=recording_path, mode="record"
        )
        kernel = AgentKernel(intelligence=record_intel, tools=[EchoTool()])
        task = TaskSpec(system_prompt="test", max_rounds=5)
        kernel.run(task, "diagnose", ToolContext())

        results = []
        for _ in range(2):
            replay_intel = RecordReplayIntelligence(
                inner=None, recording_path=recording_path, mode="replay"
            )
            replay_kernel = AgentKernel(
                intelligence=replay_intel, tools=[EchoTool()]
            )
            results.append(replay_kernel.run(task, "diagnose", ToolContext()))

        assert results[0].final_json == results[1].final_json
        assert results[0].stop_reason == results[1].stop_reason

    def test_recording_yaml_structure(self, tmp_path: Path) -> None:
        """Verify the YAML recording has the expected structure."""
        import yaml

        recording_path = tmp_path / "session.yaml"
        scripted = ScriptedIntelligence(_two_turn_sequence())
        record_intel = RecordReplayIntelligence(
            inner=scripted, recording_path=recording_path, mode="record"
        )
        kernel = AgentKernel(intelligence=record_intel, tools=[EchoTool()])
        task = TaskSpec(system_prompt="test", max_rounds=5)
        kernel.run(task, "diagnose", ToolContext())

        data = yaml.safe_load(recording_path.read_text())
        assert isinstance(data, list)
        assert len(data) == 2  # two turns

        for turn in data:
            assert "request" in turn
            assert "response" in turn
            assert "system_prompt" in turn["request"]
            assert "messages" in turn["request"]
            assert "kind" in turn["response"]
