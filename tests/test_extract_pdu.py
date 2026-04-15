from pathlib import Path

from traceweaver.ingest import extract_pdu_sessions, extract_ue_sessions

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "pcap"


def test_extract_pdu_sessions_builds_success_flow() -> None:
    extracted = extract_pdu_sessions(FIXTURES_DIR / "02_registration_and_pdu_session_success.pcapng")

    assert extracted.pdu_session_count == 1
    flow = extracted.pdu_sessions[0]
    assert flow.pdu_session_id == "1"
    assert {event.event_name for event in flow.events} >= {
        "PDU_SESSION_ESTABLISHMENT_REQUEST",
        "PDU_SESSION_ESTABLISHMENT_ACCEPT",
    }
    assert any(call.service == "nsmf-pdusession" for call in flow.sbi_calls)
    assert flow.pfcp_flow_count > 0


def test_extract_pdu_sessions_builds_release_flow() -> None:
    extracted = extract_pdu_sessions(FIXTURES_DIR / "13_pdu_session_release.pcapng")

    assert extracted.pdu_session_count >= 1
    names = {event.event_name for flow in extracted.pdu_sessions for event in flow.events}
    assert "PDU_SESSION_RELEASE_REQUEST" in names
    assert "PDU_SESSION_RELEASE_COMPLETE" in names


def test_extract_pdu_sessions_attaches_pfcp_failure_retry_flow() -> None:
    extracted = extract_pdu_sessions(FIXTURES_DIR / "07_pfcp_failure.pcapng")

    assert extracted.pdu_session_count >= 1
    assert any(flow.pfcp_flow_count > 0 for flow in extracted.pdu_sessions)
    assert any(call.service == "nsmf-pdusession" for flow in extracted.pdu_sessions for call in flow.sbi_calls)


def test_extract_ue_sessions_include_pdu_sessions() -> None:
    extracted = extract_ue_sessions(FIXTURES_DIR / "02_registration_and_pdu_session_success.pcapng")

    assert extracted.session_count == 1
    assert extracted.sessions[0].pdu_session_count == 1
