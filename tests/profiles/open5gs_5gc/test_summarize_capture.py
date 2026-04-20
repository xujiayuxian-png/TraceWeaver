"""Unit tests for summarize_capture tool (the first-call diagnostic aid)."""
from __future__ import annotations

from tests.profiles.open5gs_5gc.conftest import make_record

from traceweaver.core.tools.base import ToolContext
from traceweaver.profiles.open5gs_5gc.tools.summarize_capture import (
    SummarizeCaptureTool,
)


def _run(handle):
    return SummarizeCaptureTool().run(ToolContext(source_handle=handle))


# ---- basic shape ----------------------------------------------------


def test_empty_capture_returns_hint(enriched_handle):
    handle = enriched_handle([])
    result = _run(handle)
    assert result.data["total_records"] == 0
    assert "hint" in result.data


def test_no_source_handle_returns_hint():
    result = SummarizeCaptureTool().run(ToolContext(source_handle=None))
    assert result.data["total_records"] == 0


# ---- event_inventory and capture_signals ----------------------------


def test_clean_registration_success_signals(enriched_handle):
    """Pure registration success: no deregistration, no failures."""
    handle = enriched_handle([
        make_record(seq=1, ran="1", mm_type=65),   # REGISTRATION_REQUEST
        make_record(seq=2, ran="1", mm_type=86),   # AUTHENTICATION_REQUEST
        make_record(seq=3, ran="1", mm_type=87),   # AUTHENTICATION_RESPONSE
        make_record(seq=4, ran="1", mm_type=93),   # SECURITY_MODE_COMMAND
        make_record(seq=5, ran="1", mm_type=94),   # SECURITY_MODE_COMPLETE
        make_record(seq=6, ran="1", amf="1", mm_type=66),  # REGISTRATION_ACCEPT
    ])
    result = _run(handle)
    inv = result.data["event_inventory"]
    assert inv["REGISTRATION_REQUEST"] == 1
    assert inv["REGISTRATION_ACCEPT"] == 1

    signals = result.data["capture_signals"]
    assert signals["has_registration"] is True
    assert signals["has_deregistration"] is False
    assert signals["has_authentication_failure"] is False
    assert signals["has_registration_reject"] is False
    assert signals["ran_ue_ngap_id_count"] == 1
    assert signals["multiple_ran_ue_ngap_ids"] is False


def test_has_deregistration_flag(enriched_handle):
    """This is the T8 blind spot: deregistration must be flagged."""
    handle = enriched_handle([
        make_record(seq=1, ran="1", mm_type=65),  # REGISTRATION_REQUEST
        make_record(seq=2, ran="1", amf="1", mm_type=66),  # REGISTRATION_ACCEPT
        make_record(seq=3, ran="1", amf="1", mm_type=69),  # DEREGISTRATION_REQUEST_UE_ORIG
        make_record(seq=4, ran="1", amf="1", mm_type=70),  # DEREGISTRATION_ACCEPT_UE_ORIG
    ])
    result = _run(handle)
    inv = result.data["event_inventory"]
    assert inv["DEREGISTRATION_REQUEST_UE_ORIG"] == 1
    assert inv["DEREGISTRATION_ACCEPT_UE_ORIG"] == 1

    signals = result.data["capture_signals"]
    assert signals["has_deregistration"] is True


def test_has_deactivation_flag(enriched_handle):
    rec1 = make_record(seq=1, ran="1", mm_type=65)
    rec2 = make_record(seq=2, ran="1")
    rec2.fields["event"] = "DEACTIVATION_REQUEST"
    handle = enriched_handle([rec1, rec2])
    result = _run(handle)
    signals = result.data["capture_signals"]
    assert signals["has_deactivation"] is True
    assert signals["has_deregistration_or_deactivation"] is True
    assert any(
        "deregistration/deactivation" in g
        for g in result.data["verdict_guardrails"]
    )


def test_pfcp_setup_unbalanced_flag(enriched_handle):
    """T4-style scenario: PFCP SETUP REQUEST with no matching RESPONSE."""
    handle = enriched_handle([
        make_record(seq=1, ran="1", mm_type=65),  # REG_REQUEST
        make_record(seq=2, ran="1", amf="1", mm_type=66),  # REG_ACCEPT
        make_record(seq=3, pfcp_msg_type=50),  # SESSION_ESTABLISHMENT_REQUEST
        # NO matching response => unbalanced
    ])
    result = _run(handle)
    signals = result.data["capture_signals"]
    assert signals["pfcp_setup_request_count"] == 1
    assert signals["pfcp_setup_response_count"] == 0
    assert signals["pfcp_setup_unbalanced"] is True
    assert signals["likely_pfcp_failure"] is True
    assert any("get_pfcp_exchanges" in g for g in result.data["verdict_guardrails"])


def test_pfcp_setup_balanced(enriched_handle):
    """Complete PFCP exchange: req + resp, not unbalanced."""
    handle = enriched_handle([
        make_record(seq=1, pfcp_msg_type=50),  # SESSION_ESTABLISHMENT_REQUEST
        make_record(seq=2, pfcp_msg_type=51),  # SESSION_ESTABLISHMENT_RESPONSE
    ])
    result = _run(handle)
    signals = result.data["capture_signals"]
    assert signals["pfcp_setup_request_count"] == 1
    assert signals["pfcp_setup_response_count"] == 1
    assert signals["pfcp_setup_unbalanced"] is False


def test_multiple_ran_ue_ngap_ids_retry_scenario(enriched_handle):
    """T9-style scenario: same UE retries with a new ran_ue_ngap_id."""
    handle = enriched_handle([
        make_record(seq=1, ran="1", mm_type=65),  # first REGISTRATION_REQUEST
        make_record(seq=2, ran="1", mm_type=89),  # AUTHENTICATION_FAILURE
        make_record(seq=3, ran="2", mm_type=65),  # retry, new ran id
        make_record(seq=4, ran="2", amf="2", mm_type=66),  # REGISTRATION_ACCEPT
    ])
    result = _run(handle)
    signals = result.data["capture_signals"]
    assert signals["ran_ue_ngap_id_count"] == 2
    assert signals["multiple_ran_ue_ngap_ids"] is True
    assert signals["has_authentication_failure"] is True
    # Overview must list both ids in temporal order
    overview = result.data["ue_overview"]
    assert [u["ran_ue_ngap_id"] for u in overview] == ["1", "2"]
    # First UE: REG_REQUEST + AUTH_FAILURE
    assert "AUTHENTICATION_FAILURE" in overview[0]["events"]
    # Second UE: REG_REQUEST + REG_ACCEPT
    assert "REGISTRATION_ACCEPT" in overview[1]["events"]
    assert signals["retry_pattern_present"] is True
    assert any("retry" in g.lower() for g in result.data["verdict_guardrails"])


def test_registration_reject_flag(enriched_handle):
    handle = enriched_handle([
        make_record(seq=1, ran="1", mm_type=65),
        make_record(seq=2, ran="1", mm_type=68, mm_cause=11),  # REGISTRATION_REJECT
    ])
    result = _run(handle)
    signals = result.data["capture_signals"]
    assert signals["has_registration_reject"] is True


def test_http_status_inventory(enriched_handle):
    handle = enriched_handle([
        make_record(seq=1, http2_method="POST", http2_path="/nausf-auth/v1", http2_status="200"),
        make_record(seq=2, http2_method="POST", http2_path="/nudm-sdm/v2", http2_status="500"),
        make_record(seq=3, http2_method="GET", http2_path="/nudm-sdm/v2", http2_status="404"),
    ])
    result = _run(handle)
    inv = result.data["http_status_inventory"]
    assert inv["200"] == 1
    assert inv["500"] == 1
    assert inv["404"] == 1
    signals = result.data["capture_signals"]
    assert signals["has_sbi_http_5xx"] is True
    assert signals["has_sbi_http_4xx"] is True
    assert signals["has_sbi_http_failure"] is True
    assert signals["likely_sbi_failure"] is True
    assert any("get_sbi_calls" in g for g in result.data["verdict_guardrails"])


def test_pdu_session_setup_signals(enriched_handle):
    """If setup started but not completed, the flag must flip."""
    handle = enriched_handle([
        make_record(seq=1, ran="1", sm_type=193),  # PDU_SESSION_ESTABLISHMENT_REQUEST
        # no ESTABLISHMENT_ACCEPT, no NGAP_PDU_SESSION_RESOURCE_SETUP
    ])
    result = _run(handle)
    signals = result.data["capture_signals"]
    assert signals["pdu_session_setup_started"] is True
    assert signals["pdu_session_setup_completed"] is False


def test_time_span(enriched_handle):
    handle = enriched_handle([
        make_record(seq=1, timestamp=1000.0, ran="1", mm_type=65),
        make_record(seq=2, timestamp=1005.5, ran="1", mm_type=66),
    ])
    result = _run(handle)
    assert result.data["time_span_s"] == 5.5


def test_interpretation_hint_present(enriched_handle):
    """The hint text must ship so the LLM sees reconciliation guidance."""
    handle = enriched_handle([make_record(seq=1, ran="1", mm_type=65)])
    result = _run(handle)
    assert "_interpretation_hint" in result.data
    assert "Reconcile" in result.data["_interpretation_hint"]


def test_ue_overview_truncates_long_event_lists(enriched_handle):
    """Per-UE event list is capped to avoid prompt bloat."""
    records = [
        make_record(seq=i, ran="1", mm_type=65)  # 25 REGISTRATION_REQUEST events
        for i in range(1, 26)
    ]
    handle = enriched_handle(records)
    result = _run(handle)
    overview = result.data["ue_overview"]
    assert len(overview) == 1
    # Per-UE list capped at 20
    assert len(overview[0]["events"]) == 20
    # But the total event_inventory count is still accurate
    assert result.data["event_inventory"]["REGISTRATION_REQUEST"] == 25
