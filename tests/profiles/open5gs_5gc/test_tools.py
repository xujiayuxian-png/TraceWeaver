"""Unit tests for the five 5GC profile tools (no LLM involved)."""

from __future__ import annotations

from tests.profiles.open5gs_5gc.conftest import make_record

from traceweaver.core.tools.base import ToolContext
from traceweaver.profiles.open5gs_5gc.tools.get_nas_cause_meaning import (
    GetNasCauseMeaningTool,
)
from traceweaver.profiles.open5gs_5gc.tools.get_pfcp_exchanges import (
    GetPFCPExchangesTool,
)
from traceweaver.profiles.open5gs_5gc.tools.get_sbi_calls import GetSBICallsTool
from traceweaver.profiles.open5gs_5gc.tools.get_ue_timeline import GetUETimelineTool
from traceweaver.profiles.open5gs_5gc.tools.list_ue_sessions import ListUESessionsTool


# ---- list_ue_sessions -----------------------------------------------

def test_list_ue_sessions_groups_by_ngap_ids(enriched_handle) -> None:
    handle = enriched_handle(
        [
            make_record(seq=1, ran="1", amf="1", mm_type=65),  # REG_REQUEST
            make_record(seq=2, ran="1", amf="1", mm_type=68, mm_cause=20),  # REJECT
            make_record(seq=3, ran="2", amf="2", mm_type=65),
            make_record(seq=4, ran="2", amf="2", mm_type=66),  # ACCEPT
        ]
    )
    tool = ListUESessionsTool()
    result = tool.run(ToolContext(source_handle=handle))
    assert result.data["count"] == 2
    first = result.data["sessions"][0]
    assert first["ran_ue_ngap_id"] == "1"
    assert first["first_event"] == "REGISTRATION_REQUEST"
    assert first["last_event"] == "REGISTRATION_REJECT"
    assert first["event_counts"]["REGISTRATION_REQUEST"] == 1


def test_list_ue_sessions_groups_when_amf_id_absent_on_first_frame(
    enriched_handle,
) -> None:
    """Real captures start with REGISTRATION_REQUEST (no AMF id yet)."""
    handle = enriched_handle(
        [
            make_record(seq=1, ran="1", amf=None, mm_type=65),  # pre-AMF-id
            make_record(seq=2, ran="1", amf="6", mm_type=68, mm_cause=9),
        ]
    )
    result = ListUESessionsTool().run(ToolContext(source_handle=handle))
    assert result.data["count"] == 1
    s = result.data["sessions"][0]
    assert s["ran_ue_ngap_id"] == "1"
    assert s["amf_ue_ngap_id"] == "6"
    assert s["frames"] == 2
    assert s["last_event"] == "REGISTRATION_REJECT"


def test_list_ue_sessions_empty(enriched_handle) -> None:
    handle = enriched_handle([make_record(seq=1, pfcp_msg_type=1)])
    result = ListUESessionsTool().run(ToolContext(source_handle=handle))
    assert result.data["count"] == 0
    assert "hint" in result.data


def test_list_ue_sessions_no_source() -> None:
    result = ListUESessionsTool().run(ToolContext())
    assert result.data["count"] == 0
    assert "hint" in result.data


# ---- get_ue_timeline ------------------------------------------------

def test_timeline_filters_by_ran(enriched_handle) -> None:
    handle = enriched_handle(
        [
            make_record(seq=1, ran="1", amf="1", mm_type=65),
            make_record(seq=2, ran="2", amf="2", mm_type=65),
            make_record(seq=3, ran="1", amf="1", mm_type=68, mm_cause=20),
        ]
    )
    result = GetUETimelineTool().run(
        ToolContext(source_handle=handle), ran_ue_ngap_id="1"
    )
    assert result.data["count"] == 2
    assert [e["event"] for e in result.data["events"]] == [
        "REGISTRATION_REQUEST",
        "REGISTRATION_REJECT",
    ]
    assert result.data["events"][-1]["mm_cause"] == 20


def test_timeline_requires_ue_id(enriched_handle) -> None:
    handle = enriched_handle([make_record(seq=1, ran="1", amf="1", mm_type=65)])
    result = GetUETimelineTool().run(ToolContext(source_handle=handle))
    assert result.data["count"] == 0
    assert "hint" in result.data


def test_timeline_honors_limit(enriched_handle) -> None:
    handle = enriched_handle(
        [make_record(seq=i, ran="1", amf="1", mm_type=65) for i in range(1, 6)]
    )
    result = GetUETimelineTool().run(
        ToolContext(source_handle=handle), ran_ue_ngap_id="1", limit=3
    )
    assert result.data["count"] == 3


def test_timeline_appends_teardown_finding(enriched_handle) -> None:
    handle = enriched_handle(
        [
            make_record(seq=1, ran="1", amf="1", mm_type=65),
            make_record(seq=2, ran="1", amf="1", proc=29),
            make_record(seq=3, ran="1", amf="1", proc=41),
        ]
    )
    result = GetUETimelineTool().run(
        ToolContext(source_handle=handle), ran_ue_ngap_id="1"
    )
    assert [e["event"] for e in result.data["events"]] == [
        "REGISTRATION_REQUEST",
        "NGAP_PDU_SESSION_RESOURCE_SETUP",
        "NGAP_UE_CONTEXT_RELEASE",
        "DEREGISTRATION_OR_SESSION_TEARDOWN",
    ]
    assert result.data["events"][-1]["seq"] == 3


def test_timeline_does_not_duplicate_explicit_deregistration(enriched_handle) -> None:
    handle = enriched_handle(
        [
            make_record(seq=1, ran="1", amf="1", mm_type=65),
            make_record(seq=2, ran="1", amf="1", mm_type=69),
        ]
    )
    result = GetUETimelineTool().run(
        ToolContext(source_handle=handle), ran_ue_ngap_id="1"
    )
    assert [e["event"] for e in result.data["events"]] == [
        "REGISTRATION_REQUEST",
        "DEREGISTRATION_REQUEST_UE_ORIG",
    ]


def test_timeline_appends_pdu_failure_hint_for_single_ue_capture(enriched_handle) -> None:
    handle = enriched_handle(
        [
            make_record(seq=1, ran="1", amf="1", mm_type=65),
            make_record(seq=2, ran="1", amf="1", proc=46),
            make_record(seq=10, sm_type=193, pdu_session_id="1"),
            make_record(seq=11, sm_type=193, pdu_session_id="1"),
            make_record(
                seq=12,
                http2_method="POST",
                http2_path="/nsmf-pdusession/v1/sm-contexts",
                http2_status="400",
                http2_streamid="1",
                tcp_stream="1",
            ),
        ]
    )
    result = GetUETimelineTool().run(
        ToolContext(source_handle=handle), ran_ue_ngap_id="1"
    )
    assert result.data["events"][-1]["event"] == "PDU_SESSION_ESTABLISHMENT_REJECT_HINT"
    assert result.data["events"][-1]["seq"] == 11


# ---- get_sbi_calls --------------------------------------------------

def test_sbi_collapses_streams(enriched_handle) -> None:
    handle = enriched_handle(
        [
            make_record(
                seq=1,
                tcp_stream="0",
                http2_streamid="1",
                http2_method="POST",
                http2_path="/namf-comm/v1/ue-contexts",
                tcp_srcport=33333,
                tcp_dstport=7777,
                frame_protocols="eth:ip:tcp:http2",
            ),
            make_record(
                seq=2,
                tcp_stream="0",
                http2_streamid="1",
                http2_status="500",
                tcp_srcport=7777,
                tcp_dstport=33333,
                frame_protocols="eth:ip:tcp:http2",
            ),
        ]
    )
    result = GetSBICallsTool().run(ToolContext(source_handle=handle))
    assert result.data["count"] == 1
    call = result.data["calls"][0]
    assert call["method"] == "POST"
    assert call["path"] == "/namf-comm/v1/ue-contexts"
    assert call["status"] == 500


def test_sbi_skips_data_continuation_frames(enriched_handle) -> None:
    """Frames on a stream with no method/path/status headers are noise."""
    handle = enriched_handle(
        [
            make_record(
                seq=1, tcp_stream="0", http2_streamid="1",
                http2_method="POST", http2_path="/nausf-auth/v1/ue-authentications",
                frame_protocols="eth:ip:tcp:http2",
            ),
            make_record(
                seq=2, tcp_stream="0", http2_streamid="5",
                frame_protocols="eth:ip:tcp:http2",
            ),
        ]
    )
    result = GetSBICallsTool().run(ToolContext(source_handle=handle))
    assert result.data["count"] == 1
    assert result.data["calls"][0]["path"] == "/nausf-auth/v1/ue-authentications"


def test_sbi_filters_by_path(enriched_handle) -> None:
    handle = enriched_handle(
        [
            make_record(
                seq=1, tcp_stream="0", http2_streamid="1",
                http2_method="GET", http2_path="/nudm-sdm/v2/x/am-data",
                frame_protocols="eth:ip:tcp:http2",
            ),
            make_record(
                seq=2, tcp_stream="0", http2_streamid="3",
                http2_method="POST", http2_path="/namf-comm/v1/ue-contexts",
                frame_protocols="eth:ip:tcp:http2",
            ),
        ]
    )
    result = GetSBICallsTool().run(
        ToolContext(source_handle=handle), path_contains="nudm"
    )
    assert result.data["count"] == 1
    assert "nudm" in result.data["calls"][0]["path"]


# ---- get_pfcp_exchanges --------------------------------------------

def test_pfcp_basic(enriched_handle) -> None:
    handle = enriched_handle(
        [
            make_record(seq=1, pfcp_msg_type=50, pfcp_seid="0x1", pfcp_cause="1"),
            make_record(seq=2, pfcp_msg_type=51, pfcp_seid="0x1", pfcp_cause="1"),
            make_record(seq=3, pfcp_msg_type=1),
        ]
    )
    result = GetPFCPExchangesTool().run(ToolContext(source_handle=handle))
    assert result.data["count"] == 3
    assert result.data["exchanges"][0]["msg_name"] == "SESSION_ESTABLISHMENT_REQUEST"


def test_pfcp_filter_by_name(enriched_handle) -> None:
    handle = enriched_handle(
        [
            make_record(seq=1, pfcp_msg_type=50),
            make_record(seq=2, pfcp_msg_type=1),
        ]
    )
    result = GetPFCPExchangesTool().run(
        ToolContext(source_handle=handle), msg_name_contains="HEARTBEAT"
    )
    assert result.data["count"] == 1


# ---- get_nas_cause_meaning -----------------------------------------

def test_nas_cause_hits() -> None:
    tool = GetNasCauseMeaningTool()
    assert tool.run(ToolContext(), code=20, layer="5gmm").data["name"] == "MAC failure"
    assert (
        tool.run(ToolContext(), code=22, layer="5gmm").data["category"] == "capacity"
    )
    assert (
        tool.run(ToolContext(), code=27, layer="5gsm").data["name"]
        == "Missing or unknown DNN"
    )


def test_nas_cause_miss_returns_hint() -> None:
    tool = GetNasCauseMeaningTool()
    result = tool.run(ToolContext(), code=999, layer="5gmm")
    assert "hint" in result.data
    assert "name" not in result.data


def test_nas_cause_bad_layer() -> None:
    result = GetNasCauseMeaningTool().run(ToolContext(), code=1, layer="eps")
    assert "hint" in result.data
