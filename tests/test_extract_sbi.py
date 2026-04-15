from pathlib import Path

from traceweaver.ingest import extract_sbi_calls, extract_ue_sessions

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "pcap"


def test_extract_sbi_calls_pairs_request_and_response() -> None:
    extracted = extract_sbi_calls(FIXTURES_DIR / "02_registration_and_pdu_session_success.pcapng")

    call = next(call for call in extracted.calls if call.path == "/nausf-auth/v1/ue-authentications")
    assert call.method == "POST"
    assert call.status == 201
    assert call.request_frame is not None
    assert call.response_frame is not None


def test_extract_ue_sessions_attaches_identity_bearing_sbi_calls() -> None:
    extracted = extract_ue_sessions(FIXTURES_DIR / "02_registration_and_pdu_session_success.pcapng")

    assert extracted.session_count == 1
    session = extracted.sessions[0]
    paths = {call.path for call in session.sbi_calls if call.path}
    assert "/nudm-ueau/v1/suci-0-001-01-0000-0-0-0000000210/security-information/generate-auth-data" in paths
    assert session.suci == "suci-0-001-01-0000-0-0-0000000210"
    assert session.supi == "imsi-001010000000210"


def test_extract_ue_sessions_attaches_sbi_failure_call() -> None:
    extracted = extract_ue_sessions(FIXTURES_DIR / "08_sbi_failure.pcapng")

    assert extracted.session_count >= 1
    all_paths = {call.path for session in extracted.sessions for call in session.sbi_calls if call.path}
    assert "/nausf-auth/v1/ue-authentications" in all_paths
