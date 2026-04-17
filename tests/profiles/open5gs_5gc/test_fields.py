"""Static sanity checks on the 5GC field catalogue."""

from __future__ import annotations

from traceweaver.profiles.open5gs_5gc.fields import (
    EVENT_MM_MAP,
    EVENT_NGAP_MAP,
    EVENT_SM_MAP,
    EXTRACT_FIELDS,
    PFCP_MSG_MAP,
)


def test_extract_fields_are_tuple_of_strings() -> None:
    assert isinstance(EXTRACT_FIELDS, tuple)
    assert all(isinstance(f, str) for f in EXTRACT_FIELDS)


def test_extract_fields_cover_essential_protocols() -> None:
    required = {
        "ngap.procedureCode",
        "nas-5gs.mm.message_type",
        "nas-5gs.mm.5gmm_cause",
        "nas-5gs.sm.message_type",
        "nas-5gs.sm.5gsm_cause",
        "http2.headers.status",
        "http2.streamid",
        "pfcp.msg_type",
        "pfcp.cause",
    }
    missing = required - set(EXTRACT_FIELDS)
    assert not missing, f"missing essential fields: {missing}"


def test_event_maps_have_headline_entries() -> None:
    assert EVENT_MM_MAP[65] == "REGISTRATION_REQUEST"
    assert EVENT_MM_MAP[68] == "REGISTRATION_REJECT"
    assert EVENT_MM_MAP[89] == "AUTHENTICATION_FAILURE"
    assert EVENT_SM_MAP[193] == "PDU_SESSION_ESTABLISHMENT_REQUEST"
    assert EVENT_SM_MAP[195] == "PDU_SESSION_ESTABLISHMENT_REJECT"
    assert EVENT_NGAP_MAP[14] == "NGAP_INITIAL_CONTEXT_SETUP"


def test_pfcp_msg_map_covers_core_flows() -> None:
    assert PFCP_MSG_MAP[50] == "SESSION_ESTABLISHMENT_REQUEST"
    assert PFCP_MSG_MAP[51] == "SESSION_ESTABLISHMENT_RESPONSE"
    assert PFCP_MSG_MAP[1] == "HEARTBEAT_REQUEST"
