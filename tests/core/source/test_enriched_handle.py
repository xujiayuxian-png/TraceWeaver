"""Tests for EnrichedSourceHandle."""

from __future__ import annotations

import pytest

from traceweaver.core.source import (
    EnrichedSourceHandle,
    Record,
    SourceSpec,
    apply_enrichers,
)
from traceweaver.core.source.fake import FakeSource


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
        key=fields.pop("key", f"k{seq}"),
        fields=fields,
    )


def _add_event(record: Record) -> Record:
    mt = record.fields.get("mt")
    event = {1: "REQ", 2: "ACCEPT", 3: "REJECT"}.get(mt)
    if event is None:
        return record
    new_fields = dict(record.fields)
    new_fields["event"] = event
    return record.model_copy(update={"fields": new_fields})


def _tag_rejects(record: Record) -> Record:
    if record.fields.get("event") != "REJECT":
        return record
    new_fields = dict(record.fields)
    new_fields["severity"] = "high"
    return record.model_copy(update={"fields": new_fields})


def test_enricher_runs_lazily_on_iter() -> None:
    inner = _handle([_rec(1, mt=1), _rec(2, mt=2)])
    wrapped = EnrichedSourceHandle(inner, [_add_event])
    rows = list(wrapped.iter_records())
    assert [r.fields["event"] for r in rows] == ["REQ", "ACCEPT"]


def test_filter_sees_enriched_fields() -> None:
    """This is the main reason enrichment-before-filter matters."""
    inner = _handle([_rec(1, mt=1), _rec(2, mt=3), _rec(3, mt=3)])
    wrapped = EnrichedSourceHandle(inner, [_add_event])
    rows = list(wrapped.iter_records(filter={"event": "REJECT"}))
    assert [r.seq for r in rows] == [2, 3]


def test_chain_applies_in_order() -> None:
    inner = _handle([_rec(1, mt=3), _rec(2, mt=2)])
    wrapped = EnrichedSourceHandle(inner, [_add_event, _tag_rejects])
    rows = list(wrapped.iter_records())
    assert rows[0].fields["severity"] == "high"
    assert "severity" not in rows[1].fields


def test_projection_happens_after_enrichment() -> None:
    inner = _handle([_rec(1, mt=1)])
    wrapped = EnrichedSourceHandle(inner, [_add_event])
    rows = list(wrapped.iter_records(fields=["event"]))
    assert rows[0].fields == {"event": "REQ"}


def test_get_records_around_enriches_window() -> None:
    inner = _handle([_rec(i, mt=i % 3 + 1) for i in range(1, 6)])
    wrapped = EnrichedSourceHandle(inner, [_add_event])
    window = wrapped.get_records_around(3, before=1, after=1)
    for r in window:
        assert "event" in r.fields


def test_limit_respected_after_filter() -> None:
    inner = _handle([_rec(i, mt=3) for i in range(1, 6)])
    wrapped = EnrichedSourceHandle(inner, [_add_event])
    rows = list(wrapped.iter_records(filter={"event": "REJECT"}, limit=2))
    assert len(rows) == 2


def test_enricher_identity_violation_rejected() -> None:
    def bad(r: Record) -> Record:
        return r.model_copy(update={"seq": r.seq + 100})

    with pytest.raises(RuntimeError, match="identity"):
        apply_enrichers(_rec(1, mt=1), [bad])


def test_empty_enricher_chain_is_noop() -> None:
    inner = _handle([_rec(1, mt=1), _rec(2, mt=2)])
    wrapped = EnrichedSourceHandle(inner, [])
    rows = list(wrapped.iter_records())
    assert [r.seq for r in rows] == [1, 2]
    assert "event" not in rows[0].fields


def test_metadata_passes_through() -> None:
    inner = _handle([_rec(1, mt=1), _rec(2, mt=2)])
    wrapped = EnrichedSourceHandle(inner, [_add_event])
    assert wrapped.metadata() == inner.metadata()
