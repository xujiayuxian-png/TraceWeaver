from pathlib import Path

from traceweaver.profiles.open5gs_5gc.assemble import build_pdu_sessions_for_ue, correlate_pfcp_to_pdu, correlate_sbi_to_sessions, group_ue_sessions, pair_sbi_calls
from traceweaver.profiles.open5gs_5gc.extract.records import extract_records

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "pcap"


def test_extract_pdu_sessions_builds_success_flow() -> None:
    records = extract_records(FIXTURES_DIR / "02_registration_and_pdu_session_success.pcapng")
    sessions = group_ue_sessions(records)
    correlate_sbi_to_sessions(pair_sbi_calls(records), sessions)
    extracted = build_pdu_sessions_for_ue(sessions[0])
    correlate_pfcp_to_pdu(records, extracted)

    assert len(extracted) == 1
    flow = extracted[0]
    assert flow.pdu_session_id == "1"
    assert {event.event_name for event in flow.events} >= {
        "PDU_SESSION_ESTABLISHMENT_REQUEST",
        "PDU_SESSION_ESTABLISHMENT_ACCEPT",
    }
    assert any(call.service == "nsmf-pdusession" for call in flow.sbi_calls)
    assert flow.pfcp_flow_count > 0


def test_extract_pdu_sessions_builds_release_flow() -> None:
    records = extract_records(FIXTURES_DIR / "13_pdu_session_release.pcapng")
    sessions = group_ue_sessions(records)
    correlate_sbi_to_sessions(pair_sbi_calls(records), sessions)
    extracted = build_pdu_sessions_for_ue(sessions[0])
    correlate_pfcp_to_pdu(records, extracted)

    assert len(extracted) >= 1
    names = {event.event_name for flow in extracted for event in flow.events}
    assert "PDU_SESSION_RELEASE_REQUEST" in names
    assert "PDU_SESSION_RELEASE_COMPLETE" in names


def test_extract_pdu_sessions_attaches_pfcp_failure_retry_flow() -> None:
    records = extract_records(FIXTURES_DIR / "07_pfcp_failure.pcapng")
    sessions = group_ue_sessions(records)
    correlate_sbi_to_sessions(pair_sbi_calls(records), sessions)
    extracted = build_pdu_sessions_for_ue(sessions[0])
    correlate_pfcp_to_pdu(records, extracted)

    assert len(extracted) >= 1
    assert any(flow.pfcp_flow_count > 0 for flow in extracted)
    assert any(call.service == "nsmf-pdusession" for flow in extracted for call in flow.sbi_calls)


def test_extract_ue_sessions_include_pdu_sessions() -> None:
    records = extract_records(FIXTURES_DIR / "02_registration_and_pdu_session_success.pcapng")
    extracted = group_ue_sessions(records)
    correlate_sbi_to_sessions(pair_sbi_calls(records), extracted)
    extracted[0].pdu_sessions = build_pdu_sessions_for_ue(extracted[0])
    correlate_pfcp_to_pdu(records, extracted[0].pdu_sessions)
    extracted[0].pdu_session_count = len(extracted[0].pdu_sessions)

    assert len(extracted) == 1
    assert extracted[0].pdu_session_count == 1
