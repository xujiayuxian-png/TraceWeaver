from pathlib import Path

from traceweaver.profiles.open5gs_5gc.assemble import correlate_sbi_to_sessions, group_ue_sessions, pair_sbi_calls
from traceweaver.profiles.open5gs_5gc.extract.records import extract_records

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "pcap"


def test_extract_ue_sessions_groups_single_registration_capture() -> None:
    records = extract_records(FIXTURES_DIR / "01_registration_success.pcapng")
    extracted = group_ue_sessions(records)
    correlate_sbi_to_sessions(pair_sbi_calls(records), extracted)

    assert len(extracted) == 1
    session = extracted[0]
    assert session.ran_ue_ngap_id == "1"
    assert session.amf_ue_ngap_id == "2"
    assert "REGISTRATION_REQUEST" in {event.event_name for event in session.events}


def test_extract_ue_sessions_groups_multi_ue_capture() -> None:
    records = extract_records(FIXTURES_DIR / "09_multi_ue_concurrent.pcapng")
    extracted = group_ue_sessions(records)
    correlate_sbi_to_sessions(pair_sbi_calls(records), extracted)

    assert len(extracted) == 3
    assert {session.ran_ue_ngap_id for session in extracted} == {"1", "2", "3"}
    assert {session.amf_ue_ngap_id for session in extracted} == {"3", "4", "5"}
