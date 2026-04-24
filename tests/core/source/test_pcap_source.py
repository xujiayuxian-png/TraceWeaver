"""
Tests for PcapSource.

The real tshark binary may not be available on every dev box, so we
inject a fake runner that returns canned TSV. A small real-binary smoke
test is marked `requires_tshark` and skipped if it isn't installed.
"""

from __future__ import annotations

import shutil
from typing import Sequence

import pytest

from traceweaver.core.source import SourceSpec
from traceweaver.builtin.sources.pcap import (
    PcapSource,
    parse_tshark_fields_output,
)


def _fake_runner(canned: str):
    captured: dict[str, list[str]] = {}

    def run(argv: Sequence[str]) -> str:
        captured["argv"] = list(argv)
        return canned

    run.captured = captured  # type: ignore[attr-defined]
    return run


_CANNED_TSV = (
    "frame.number\tframe.time_epoch\tip.src\tip.dst\n"
    "1\t1000.0\t10.0.0.1\t10.0.0.2\n"
    "2\t1000.5\t10.0.0.2\t10.0.0.1\n"
    "3\t1001.0\t10.0.0.1\t10.0.0.3\n"
)


def test_parse_tshark_fields_output_happy_path() -> None:
    records = parse_tshark_fields_output(
        _CANNED_TSV,
        extra_fields=["ip.src", "ip.dst"],
        key_strategy={"mode": "derived_fields", "fields": ["ip.src", "ip.dst"]},
    )
    assert [r.seq for r in records] == [1, 2, 3]
    assert records[0].timestamp == 1000.0
    assert records[0].fields["ip.src"] == "10.0.0.1"
    assert records[0].key == "10.0.0.1|10.0.0.2"


def test_parse_skips_junk_rows() -> None:
    tsv = (
        "frame.number\tframe.time_epoch\tip.src\n"
        "garbage-row\n"
        "1\t1000.0\tA\n"
    )
    records = parse_tshark_fields_output(tsv, extra_fields=["ip.src"])
    assert len(records) == 1
    assert records[0].seq == 1


def test_parse_rejects_wrong_header() -> None:
    tsv = "oops\tsomething\n1\t2\n"
    with pytest.raises(ValueError):
        parse_tshark_fields_output(tsv, extra_fields=[])


def test_pcap_source_ingest_with_fake_runner(tmp_path) -> None:
    pcap = tmp_path / "fake.pcap"
    pcap.write_bytes(b"\x00" * 16)  # just needs to exist

    runner = _fake_runner(_CANNED_TSV)
    src = PcapSource(tshark_runner=runner)
    handle = src.ingest(
        SourceSpec(
            kind="pcap",
            uri=str(pcap),
            options={
                "display_filter": "ip",
                "fields": ["ip.src", "ip.dst"],
                "key_strategy": {
                    "mode": "derived_fields",
                    "fields": ["ip.src", "ip.dst"],
                },
            },
        )
    )
    assert handle.metadata()["count"] == 3
    argv = runner.captured["argv"]
    assert argv[0] == "tshark"
    assert "-Y" in argv and "ip" in argv
    assert "-e" in argv and "ip.src" in argv and "ip.dst" in argv


def test_pcap_source_rejects_wrong_kind() -> None:
    src = PcapSource(tshark_runner=_fake_runner(""))
    with pytest.raises(ValueError):
        src.ingest(SourceSpec(kind="fake", uri="x", options={}))


def test_pcap_source_iter_with_filter_and_projection(tmp_path) -> None:
    pcap = tmp_path / "fake.pcap"
    pcap.write_bytes(b"\x00" * 16)
    src = PcapSource(tshark_runner=_fake_runner(_CANNED_TSV))
    handle = src.ingest(
        SourceSpec(
            kind="pcap",
            uri=str(pcap),
            options={"fields": ["ip.src", "ip.dst"]},
        )
    )
    rows = list(
        handle.iter_records(
            filter={"ip.src": "10.0.0.1"}, fields=["ip.dst"]
        )
    )
    assert [r.seq for r in rows] == [1, 3]
    assert set(rows[0].fields.keys()) == {"ip.dst"}


@pytest.mark.skipif(shutil.which("tshark") is None, reason="tshark not installed")
def test_pcap_source_real_tshark_noop(tmp_path) -> None:
    """A sanity check that the real runner raises on a bogus pcap path.

    We deliberately don't ship a pcap fixture in core tests — that would
    couple us to a specific protocol stack. The real-binary path is
    instead exercised in profile-level tests that do ship a pcap.
    """
    src = PcapSource()
    with pytest.raises(FileNotFoundError):
        src.ingest(
            SourceSpec(kind="pcap", uri=str(tmp_path / "does-not-exist.pcap"))
        )
