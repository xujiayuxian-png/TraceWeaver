"""Tests for FakeSource + FakeSourceHandle."""

from __future__ import annotations

import pytest

from traceweaver.core.protocols import Record, SourceSpec
from traceweaver.core.source.registry import SourceRegistry
from traceweaver.builtin.sources.fake import FakeSource


def _rec(seq: int, **fields) -> Record:
    return Record(
        source="fake",
        timestamp=1000.0 + seq,
        seq=seq,
        key=fields.pop("key", f"k{seq}"),
        fields=fields,
        raw=f"row-{seq}",
    )


def test_ingest_and_metadata() -> None:
    src = FakeSource()
    handle = src.ingest(
        SourceSpec(
            kind="fake",
            uri="memory://test",
            options={"records_object": [_rec(1, color="red"), _rec(2, color="blue")]},
        )
    )
    md = handle.metadata()
    assert md["count"] == 2
    assert md["seq_range"] == [1, 2]
    assert md["time_range"] == [1001.0, 1002.0]


def test_iter_records_filter_and_projection() -> None:
    src = FakeSource()
    handle = src.ingest(
        SourceSpec(
            kind="fake",
            uri="memory://t",
            options={
                "records_object": [
                    _rec(1, color="red", shape="square"),
                    _rec(2, color="blue", shape="circle"),
                    _rec(3, color="red", shape="triangle"),
                ]
            },
        )
    )
    rows = list(handle.iter_records(filter={"color": "red"}, fields=["color"]))
    assert [r.seq for r in rows] == [1, 3]
    assert rows[0].fields == {"color": "red"}
    assert "shape" not in rows[0].fields


def test_iter_records_limit() -> None:
    src = FakeSource()
    handle = src.ingest(
        SourceSpec(
            kind="fake",
            uri="memory://t",
            options={"records_object": [_rec(i) for i in range(1, 11)]},
        )
    )
    rows = list(handle.iter_records(limit=3))
    assert [r.seq for r in rows] == [1, 2, 3]


def test_iter_records_filter_on_toplevel_key() -> None:
    src = FakeSource()
    handle = src.ingest(
        SourceSpec(
            kind="fake",
            uri="memory://t",
            options={"records_object": [_rec(1, key="A"), _rec(2, key="B"), _rec(3, key="A")]},
        )
    )
    rows = list(handle.iter_records(filter={"key": "A"}))
    assert [r.seq for r in rows] == [1, 3]


def test_get_records_around_centers_on_anchor() -> None:
    src = FakeSource()
    handle = src.ingest(
        SourceSpec(
            kind="fake",
            uri="memory://t",
            options={"records_object": [_rec(i) for i in range(1, 11)]},
        )
    )
    window = handle.get_records_around(5, before=2, after=1)
    assert [r.seq for r in window] == [3, 4, 5, 6]


def test_get_records_around_anchor_missing_falls_back_to_nearest() -> None:
    src = FakeSource()
    handle = src.ingest(
        SourceSpec(
            kind="fake",
            uri="memory://t",
            options={"records_object": [_rec(1), _rec(5), _rec(7)]},
        )
    )
    window = handle.get_records_around(4, before=1, after=1)
    # Anchor 4 doesn't exist; insertion point is between 1 and 5, so the
    # handle widens around that index and returns the closest window.
    assert [r.seq for r in window] == [1, 5, 7]


def test_ingest_rejects_wrong_kind() -> None:
    src = FakeSource()
    with pytest.raises(ValueError):
        src.ingest(SourceSpec(kind="pcap", uri="x", options={}))


def test_registry_exposes_fake_and_pcap() -> None:
    from traceweaver.builtin import register_builtin_sources
    reg = SourceRegistry()
    register_builtin_sources(reg)
    assert reg.has("fake")
    assert reg.has("pcap")


def test_custom_registry_isolation() -> None:
    reg = SourceRegistry()
    reg.register(FakeSource())
    with pytest.raises(KeyError):
        reg.build(SourceSpec(kind="pcap", uri="x"))
    handle = reg.build(
        SourceSpec(kind="fake", uri="m://t", options={"records_object": [_rec(1)]})
    )
    assert handle.metadata()["count"] == 1
