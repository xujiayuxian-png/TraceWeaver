from pathlib import Path

from traceweaver.profiles.open5gs_5gc.assemble import correlate_sbi_to_sessions, group_ue_sessions, pair_sbi_calls
from traceweaver.profiles.open5gs_5gc.extract.records import extract_records

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "pcap"


def test_extract_sbi_calls_pairs_request_and_response() -> None:
    extracted = pair_sbi_calls(extract_records(FIXTURES_DIR / "02_registration_and_pdu_session_success.pcapng"))

    call = next(call for call in extracted if call.path == "/nausf-auth/v1/ue-authentications")
    assert call.method == "POST"
    assert call.status == 201
    assert call.request_frame is not None
    assert call.response_frame is not None


def test_extract_ue_sessions_attaches_identity_bearing_sbi_calls() -> None:
    records = extract_records(FIXTURES_DIR / "02_registration_and_pdu_session_success.pcapng")
    extracted = group_ue_sessions(records)
    correlate_sbi_to_sessions(pair_sbi_calls(records), extracted)

    assert len(extracted) == 1
    session = extracted[0]
    paths = {call.path for call in session.sbi_calls if call.path}
    assert "/nudm-ueau/v1/suci-0-001-01-0000-0-0-0000000210/security-information/generate-auth-data" in paths
    assert session.suci == "suci-0-001-01-0000-0-0-0000000210"
    assert session.supi == "imsi-001010000000210"


def test_extract_ue_sessions_attaches_sbi_failure_call() -> None:
    records = extract_records(FIXTURES_DIR / "08_sbi_failure.pcapng")
    extracted = group_ue_sessions(records)
    correlate_sbi_to_sessions(pair_sbi_calls(records), extracted)

    assert len(extracted) >= 1
    all_paths = {call.path for session in extracted for call in session.sbi_calls if call.path}
    assert "/nausf-auth/v1/ue-authentications" in all_paths
