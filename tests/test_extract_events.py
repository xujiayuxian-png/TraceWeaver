from pathlib import Path

from traceweaver.profiles.open5gs_5gc.events.identify import detect_events
from traceweaver.profiles.open5gs_5gc.extract.records import extract_records

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "pcap"


def test_extract_events_detects_registration_flow() -> None:
    extracted = detect_events(extract_records(FIXTURES_DIR / "01_registration_success.pcapng"))
    event_names = {event.event_name for event in extracted}

    assert "REGISTRATION_REQUEST" in event_names
    assert "AUTHENTICATION_REQUEST" in event_names
    assert "AUTHENTICATION_RESPONSE" in event_names
    assert "SECURITY_MODE_COMMAND" in event_names


def test_extract_events_detects_pdu_session_flow() -> None:
    extracted = detect_events(extract_records(FIXTURES_DIR / "02_registration_and_pdu_session_success.pcapng"))
    event_names = {event.event_name for event in extracted}

    assert "PDU_SESSION_ESTABLISHMENT_REQUEST" in event_names
    assert "PDU_SESSION_ESTABLISHMENT_ACCEPT" in event_names


def test_extract_events_detects_registration_reject() -> None:
    extracted = detect_events(extract_records(FIXTURES_DIR / "03_registration_reject.pcapng"))
    event_names = {event.event_name for event in extracted}

    assert "REGISTRATION_REJECT" in event_names
