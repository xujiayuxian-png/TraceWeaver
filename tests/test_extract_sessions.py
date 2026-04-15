from pathlib import Path

from traceweaver.ingest import extract_ue_sessions

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "pcap"


def test_extract_ue_sessions_groups_single_registration_capture() -> None:
    extracted = extract_ue_sessions(FIXTURES_DIR / "01_registration_success.pcapng")

    assert extracted.session_count == 1
    session = extracted.sessions[0]
    assert session.ran_ue_ngap_id == "1"
    assert session.amf_ue_ngap_id == "2"
    assert "REGISTRATION_REQUEST" in {event.event_name for event in session.events}


def test_extract_ue_sessions_groups_multi_ue_capture() -> None:
    extracted = extract_ue_sessions(FIXTURES_DIR / "09_multi_ue_concurrent.pcapng")

    assert extracted.session_count == 3
    assert {session.ran_ue_ngap_id for session in extracted.sessions} == {"1", "2", "3"}
    assert {session.amf_ue_ngap_id for session in extracted.sessions} == {"3", "4", "5"}
