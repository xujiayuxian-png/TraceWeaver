from pathlib import Path

import pytest

from traceweaver.core import inspect_capture

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "pcap"


def test_inspect_capture_reads_basic_metadata() -> None:
    inspection = inspect_capture(FIXTURES_DIR / "01_registration_success.pcapng")

    assert inspection.file_name == "01_registration_success.pcapng"
    assert inspection.packet_count > 0
    assert inspection.file_size_bytes > 0
    assert inspection.duration_seconds > 0
    assert inspection.protocols.ngap is True
    assert inspection.protocols.nas_5gs is True


def test_inspect_capture_rejects_missing_file() -> None:
    with pytest.raises(FileNotFoundError):
        inspect_capture(FIXTURES_DIR / "missing-file.pcapng")
