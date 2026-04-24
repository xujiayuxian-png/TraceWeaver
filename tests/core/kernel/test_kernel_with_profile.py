"""
Integration test for AgentKernel.run_with_profile.

Exercises the M2 end-to-end wiring without touching litellm or a real
LLM: a scripted intelligence emits a `query_records` call, then a
`search_knowledge` call, then a final answer. We assert that:

  - the built-in tools received a ToolContext carrying the profile's
    source_handle + knowledge_store,
  - the kernel assembled a TaskSpec from profile.llm,
  - the final answer round-trips cleanly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from traceweaver.core.protocols import (
    Intelligence, IntelligenceRequest, IntelligenceResponse, Record, SourceSpec, ToolCall
)
from traceweaver.core.kernel import AgentKernel
from traceweaver.builtin.knowledge.file_store import FileKnowledgeStore
from traceweaver.core.profile import load_profile_from_dir
from traceweaver.builtin.sources.fake import FakeSource
from traceweaver.builtin import register_builtin_tools
from traceweaver.core.tools.registry import ToolRegistry


FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "profiles" / "minimal"


@dataclass
class ScriptedIntelligence(Intelligence):
    name: str = "scripted"
    queue: list[IntelligenceResponse] = field(default_factory=list)
    calls: list[IntelligenceRequest] = field(default_factory=list)

    def think(self, request: IntelligenceRequest) -> IntelligenceResponse:  # type: ignore[override]
        self.calls.append(request)
        assert self.queue, "scripted intelligence exhausted"
        return self.queue.pop(0)


def test_kernel_with_profile_wires_source_and_knowledge() -> None:
    profile = load_profile_from_dir(FIXTURE)

    handle = FakeSource().ingest(
        SourceSpec(
            kind="fake",
            uri="memory://test",
            options={
                "records_object": [
                    Record(source="fake", timestamp=1.0, seq=1, fields={"color": "red"}),
                    Record(source="fake", timestamp=2.0, seq=2, fields={"color": "blue"}),
                ]
            },
        )
    )
    store = FileKnowledgeStore(items=profile.knowledge)

    registry = ToolRegistry()
    register_builtin_tools(registry)

    intelligence = ScriptedIntelligence(
        queue=[
            IntelligenceResponse(
                kind="tool_calls",
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="query_records",
                        arguments={"filter": {"color": "red"}, "fields": ["color"]},
                    )
                ],
            ),
            IntelligenceResponse(
                kind="tool_calls",
                tool_calls=[
                    ToolCall(
                        id="c2",
                        name="search_knowledge",
                        arguments={"query": "registration reject"},
                    )
                ],
            ),
            IntelligenceResponse(
                kind="final",
                final_text=json.dumps({"answer": "red frame is 1"}),
                final_json={"answer": "red frame is 1"},
            ),
        ]
    )

    kernel = AgentKernel(intelligence, list(registry))
    result = kernel.run_with_profile(
        profile,
        user_request="Find the red frame and check the registration reject docs.",
        source_handle=handle,
        knowledge_store=store,
        response_schema={"type": "object", "required": ["answer"]},
    )

    assert result.stop_reason == "final"
    assert result.final_json == {"answer": "red frame is 1"}

    first_request = intelligence.calls[0]
    assert "minimal test assistant" in first_request.system_prompt.lower()

    tool_events = [ev for ev in result.trace.events if ev.tool_executions]
    assert len(tool_events) == 2
    qr_exec = tool_events[0].tool_executions[0]
    assert qr_exec.ok is True
    assert qr_exec.data["count"] == 1
    sk_exec = tool_events[1].tool_executions[0]
    assert sk_exec.ok is True
    assert sk_exec.data["count"] >= 1


def test_kernel_with_profile_uses_profile_max_rounds() -> None:
    profile = load_profile_from_dir(FIXTURE)
    registry = ToolRegistry()
    register_builtin_tools(registry)

    intelligence = ScriptedIntelligence(
        queue=[
            IntelligenceResponse(
                kind="tool_calls",
                tool_calls=[
                    ToolCall(id=f"c{i}", name="search_knowledge", arguments={"query": "x"})
                ],
            )
            for i in range(profile.llm.max_rounds)
        ]
    )
    kernel = AgentKernel(intelligence, list(registry))
    result = kernel.run_with_profile(
        profile,
        "loop",
        knowledge_store=FileKnowledgeStore.empty(),
    )
    assert result.stop_reason == "max_rounds"
    assert len(intelligence.calls) == profile.llm.max_rounds
