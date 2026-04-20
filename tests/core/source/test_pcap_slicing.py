"""
P1.3 tests: max_records / time_range slicing options for PcapSource.

These guarantee that large pcaps can be clipped without OOM at the
parse step, and that profile options flow through to the parser.
"""
from __future__ import annotations

from typing import Sequence

import pytest

from traceweaver.core.source import SourceSpec
from traceweaver.core.source.pcap import (
    PcapSource,
    parse_tshark_fields_output,
)


# A 10-frame canned capture spanning 10s (timestamps 1000.0 ... 1009.0)
_CANNED_TSV = "frame.number\tframe.time_epoch\tip.src\n" + "".join(
    f"{i}\t{1000.0 + (i - 1):.1f}\t10.0.0.{i}\n" for i in range(1, 11)
)


# ---- parse_tshark_fields_output unit tests -------------------------


def test_max_records_truncates_output():
    records = parse_tshark_fields_output(
        _CANNED_TSV,
        extra_fields=["ip.src"],
        max_records=3,
    )
    assert len(records) == 3
    assert [r.seq for r in records] == [1, 2, 3]


def test_max_records_zero_returns_empty():
    """max_records=0 should yield no records."""
    records = parse_tshark_fields_output(
        _CANNED_TSV,
        extra_fields=["ip.src"],
        max_records=0,
    )
    assert records == []


def test_max_records_larger_than_input_returns_all():
    records = parse_tshark_fields_output(
        _CANNED_TSV,
        extra_fields=["ip.src"],
        max_records=9999,
    )
    assert len(records) == 10


def test_max_records_none_returns_all():
    """Default (None) keeps everything."""
    records = parse_tshark_fields_output(
        _CANNED_TSV,
        extra_fields=["ip.src"],
        max_records=None,
    )
    assert len(records) == 10


def test_time_range_filters_relative_to_first_frame():
    """time_range is relative to the first frame's timestamp."""
    # Canned timestamps: 1000.0 .. 1009.0; relative: 0 .. 9
    records = parse_tshark_fields_output(
        _CANNED_TSV,
        extra_fields=["ip.src"],
        time_range=(2.0, 5.0),
    )
    # rel_ts in [2, 5] means frames 3, 4, 5, 6 (indices start at 1, ts=1002..1005)
    assert [r.seq for r in records] == [3, 4, 5, 6]


def test_time_range_start_zero_includes_first_frame():
    records = parse_tshark_fields_output(
        _CANNED_TSV,
        extra_fields=["ip.src"],
        time_range=(0.0, 2.0),
    )
    # rel_ts in [0, 2] -> frames 1, 2, 3
    assert [r.seq for r in records] == [1, 2, 3]


def test_time_range_beyond_data_returns_empty():
    records = parse_tshark_fields_output(
        _CANNED_TSV,
        extra_fields=["ip.src"],
        time_range=(100.0, 200.0),
    )
    assert records == []


def test_time_range_and_max_records_combine():
    """Both limits can be active together; whichever hits first wins."""
    records = parse_tshark_fields_output(
        _CANNED_TSV,
        extra_fields=["ip.src"],
        time_range=(0.0, 9.0),  # allows all
        max_records=4,           # but cap at 4
    )
    assert len(records) == 4
    assert [r.seq for r in records] == [1, 2, 3, 4]


# ---- PcapSource.ingest() integration ------------------------------


def _fake_runner(canned: str):
    def run(argv: Sequence[str]) -> str:
        return canned
    return run


def test_ingest_respects_max_records_from_options(tmp_path):
    """Option plumbing: source_config.max_records reaches the parser."""
    fake_pcap = tmp_path / "fake.pcap"
    fake_pcap.write_bytes(b"\x00")  # existence check only

    source = PcapSource(tshark_runner=_fake_runner(_CANNED_TSV))
    spec = SourceSpec(
        kind="pcap",
        uri=str(fake_pcap),
        options={"fields": ["ip.src"], "max_records": 2},
    )
    handle = source.ingest(spec)
    records = list(handle.iter_records())
    assert len(records) == 2


def test_ingest_respects_time_range_from_options(tmp_path):
    fake_pcap = tmp_path / "fake.pcap"
    fake_pcap.write_bytes(b"\x00")

    source = PcapSource(tshark_runner=_fake_runner(_CANNED_TSV))
    spec = SourceSpec(
        kind="pcap",
        uri=str(fake_pcap),
        options={"fields": ["ip.src"], "time_range": (3.0, 6.0)},
    )
    handle = source.ingest(spec)
    records = list(handle.iter_records())
    # rel_ts in [3, 6] -> frames 4, 5, 6, 7
    assert [r.seq for r in records] == [4, 5, 6, 7]


def test_ingest_without_slicing_options_keeps_all(tmp_path):
    """Backward compat: unconfigured => full capture."""
    fake_pcap = tmp_path / "fake.pcap"
    fake_pcap.write_bytes(b"\x00")

    source = PcapSource(tshark_runner=_fake_runner(_CANNED_TSV))
    spec = SourceSpec(
        kind="pcap",
        uri=str(fake_pcap),
        options={"fields": ["ip.src"]},
    )
    handle = source.ingest(spec)
    records = list(handle.iter_records())
    assert len(records) == 10
