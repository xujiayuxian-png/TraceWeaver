"""Tests for get_records_around built-in tool."""

from __future__ import annotations

from traceweaver.core.protocols import Record, SourceSpec, ToolContext
from traceweaver.builtin.sources.fake import FakeSource
from traceweaver.builtin.tools.get_records_around import GetRecordsAroundTool


def _handle(seqs: list[int]):
    records = [
        Record(source="fake", timestamp=1000.0 + s, seq=s, fields={"i": s})
        for s in seqs
    ]
    return FakeSource().ingest(
        SourceSpec(kind="fake", uri="memory://t", options={"records_object": records})
    )


def test_no_source_hint() -> None:
    tool = GetRecordsAroundTool()
    out = tool.run(ToolContext(), seq=5)
    assert out.data["count"] == 0
    assert "no source" in out.data["hint"]


def test_window_returns_expected_neighbors() -> None:
    handle = _handle([1, 2, 3, 4, 5])
    tool = GetRecordsAroundTool()
    out = tool.run(ToolContext(source_handle=handle), seq=3, before=1, after=2)
    seqs = [r["seq"] for r in out.data["records"]]
    assert seqs == [2, 3, 4, 5]
    assert out.data["anchor_seq"] == 3


def test_missing_seq_arg_returns_hint() -> None:
    tool = GetRecordsAroundTool()
    out = tool.run(ToolContext(source_handle=_handle([1])))
    assert "required" in out.data["hint"].lower() or "invalid arguments" in out.data["hint"].lower()


def test_window_on_empty_source_includes_hint() -> None:
    handle = _handle([])
    tool = GetRecordsAroundTool()
    out = tool.run(ToolContext(source_handle=handle), seq=1)
    assert out.data["count"] == 0
    assert "hint" in out.data


def test_window_clamps_to_available_records() -> None:
    handle = _handle([1, 2, 3])
    tool = GetRecordsAroundTool()
    out = tool.run(
        ToolContext(source_handle=handle), seq=2, before=100, after=100
    )
    assert [r["seq"] for r in out.data["records"]] == [1, 2, 3]


def test_seq_not_found_uses_insertion_point_window() -> None:
    handle = _handle([10, 20, 30, 40])
    tool = GetRecordsAroundTool()
    out = tool.run(ToolContext(source_handle=handle), seq=35, before=1, after=1)
    assert [r["seq"] for r in out.data["records"]] == [30, 40]


def test_negative_before_after_are_clamped_to_zero() -> None:
    handle = _handle([1, 2, 3])
    tool = GetRecordsAroundTool()
    out = tool.run(ToolContext(source_handle=handle), seq=2, before=-9, after=-7)
    assert [r["seq"] for r in out.data["records"]] == [2]
