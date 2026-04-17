"""Tests for query_records built-in tool."""

from __future__ import annotations

from traceweaver.core.source import Record, SourceSpec
from traceweaver.core.source.fake import FakeSource
from traceweaver.core.tools.base import ToolContext
from traceweaver.core.tools.builtin.query_records import QueryRecordsTool


def _handle(records: list[Record]):
    return FakeSource().ingest(
        SourceSpec(
            kind="fake",
            uri="memory://t",
            options={"records_object": records},
        )
    )


def _rec(seq: int, **fields) -> Record:
    return Record(
        source="fake",
        timestamp=1000.0 + seq,
        seq=seq,
        key=fields.pop("key", ""),
        fields=fields,
    )


def test_no_source_returns_hint() -> None:
    tool = QueryRecordsTool()
    out = tool.run(ToolContext(), filter={"x": 1})
    assert out.data["count"] == 0
    assert "no source" in out.data["hint"]


def test_basic_filter_and_projection() -> None:
    handle = _handle([
        _rec(1, color="red", shape="sq"),
        _rec(2, color="blue", shape="ci"),
        _rec(3, color="red", shape="tr"),
    ])
    tool = QueryRecordsTool()
    out = tool.run(
        ToolContext(source_handle=handle),
        filter={"color": "red"},
        fields=["color"],
    )
    assert out.data["count"] == 2
    assert all(r["fields"] == {"color": "red"} for r in out.data["records"])
    assert out.refs == ["fake:seq=1", "fake:seq=3"]


def test_empty_match_includes_hint() -> None:
    handle = _handle([_rec(1, x=1)])
    tool = QueryRecordsTool()
    out = tool.run(ToolContext(source_handle=handle), filter={"x": 999})
    assert out.data["count"] == 0
    assert "no records match" in out.data["hint"]


def test_limit_triggers_truncated_flag() -> None:
    handle = _handle([_rec(i) for i in range(1, 11)])
    tool = QueryRecordsTool()
    out = tool.run(ToolContext(source_handle=handle), limit=3)
    assert out.data["count"] == 3
    assert out.data["truncated"] is True
    assert out.truncated is True


def test_bad_filter_type_is_reported_not_raised() -> None:
    handle = _handle([_rec(1)])
    tool = QueryRecordsTool()
    out = tool.run(ToolContext(source_handle=handle), filter="oops")
    assert "must be an object" in out.data["hint"]
