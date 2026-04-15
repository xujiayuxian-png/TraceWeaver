from pathlib import Path

from traceweaver.ingest import extract_5gc_records

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "pcap"


def test_extract_records_reads_registration_success() -> None:
    extracted = extract_5gc_records(FIXTURES_DIR / "01_registration_success.pcapng")

    assert extracted.record_count > 0
    assert any(record.primary_protocol == "nas_5gs" for record in extracted.records)
    assert any(record.fields["ngap.RAN_UE_NGAP_ID"] for record in extracted.records)


def test_extract_records_reads_http2_and_sm_messages() -> None:
    extracted = extract_5gc_records(FIXTURES_DIR / "02_registration_and_pdu_session_success.pcapng")

    assert any(record.fields["http2.streamid"] for record in extracted.records)
    assert any(record.fields["nas_5gs.sm.message_type"] for record in extracted.records)


def test_extract_records_reads_reject_cause() -> None:
    extracted = extract_5gc_records(FIXTURES_DIR / "03_registration_reject.pcapng")

    assert any(record.fields["nas_5gs.mm.5gmm_cause"] for record in extracted.records)


def test_extract_records_limit_is_applied_after_filtering() -> None:
    extracted = extract_5gc_records(FIXTURES_DIR / "01_registration_success.pcapng", limit=5)

    assert extracted.record_count == 5
    assert extracted.records[0].frame_number >= 20
