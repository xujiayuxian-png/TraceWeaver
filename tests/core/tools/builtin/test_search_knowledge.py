"""Tests for search_knowledge built-in tool."""

from __future__ import annotations

from pathlib import Path

from traceweaver.builtin.knowledge.file_store import FileKnowledgeStore
from traceweaver.core.profile.base import ProfileKnowledgeItem
from traceweaver.core.protocols import ToolContext
from traceweaver.builtin.tools.search_knowledge import SearchKnowledgeTool


FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "profiles"
    / "minimal"
    / "knowledge"
    / "sample.md"
)


def _ctx() -> ToolContext:
    store = FileKnowledgeStore(
        items=[ProfileKnowledgeItem(path=FIXTURE, tags=["sample"])]
    )
    return ToolContext(knowledge_store=store)


def test_no_store_hint_without_retries() -> None:
    tool = SearchKnowledgeTool()
    out = tool.run(ToolContext(), query="anything")
    assert out.data["count"] == 0
    assert "no knowledge base" in out.data["hint"]


def test_query_required() -> None:
    tool = SearchKnowledgeTool()
    out = tool.run(_ctx(), query="")
    assert out.data["count"] == 0
    assert "required" in out.data["hint"]


def test_finds_relevant_section() -> None:
    tool = SearchKnowledgeTool()
    out = tool.run(_ctx(), query="registration reject")
    assert out.data["count"] >= 1
    titles = [h["title"] for h in out.data["hits"]]
    assert "Registration Reject" in titles


def test_tag_filter() -> None:
    tool = SearchKnowledgeTool()
    out = tool.run(_ctx(), query="cause", tags=["sample"])
    assert out.data["count"] >= 1
    out2 = tool.run(_ctx(), query="cause", tags=["nope"])
    assert out2.data["count"] == 0
    assert "do not retry" in out2.data["hint"].lower()


def test_no_match_hint_prevents_retry_loop() -> None:
    tool = SearchKnowledgeTool()
    out = tool.run(_ctx(), query="zzz-absurd-token-xxx")
    assert out.data["count"] == 0
    assert "do not retry" in out.data["hint"].lower()
