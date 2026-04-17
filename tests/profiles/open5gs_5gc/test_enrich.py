"""Tests for the 5GC record enricher."""

from __future__ import annotations

from tests.profiles.open5gs_5gc.conftest import make_record

from traceweaver.profiles.open5gs_5gc.enrich import enrich


def test_enrich_identifies_registration_reject() -> None:
    rec = make_record(seq=1, mm_type=68, mm_cause=20, ran="1", amf="2")
    out = enrich(rec)
    assert out.fields["event"] == "REGISTRATION_REJECT"
    assert out.fields["mm_cause"] == 20
    assert out.fields["protocol_layer"] == "nas_5gmm"
    assert out.fields["ran_ue_ngap_id"] == "1"
    assert out.fields["amf_ue_ngap_id"] == "2"


def test_enrich_identifies_pdu_session_reject() -> None:
    rec = make_record(seq=2, sm_type=195, sm_cause=27, pdu_session_id="1")
    out = enrich(rec)
    assert out.fields["event"] == "PDU_SESSION_ESTABLISHMENT_REJECT"
    assert out.fields["sm_cause"] == 27
    assert out.fields["protocol_layer"] == "nas_5gsm"
    assert out.fields["pdu_session_id"] == "1"


def test_enrich_falls_back_to_ngap_when_no_nas() -> None:
    rec = make_record(seq=3, proc=14, ran="5", frame_protocols="sctp:ngap")
    out = enrich(rec)
    assert out.fields["event"] == "NGAP_INITIAL_CONTEXT_SETUP"
    assert out.fields["protocol_layer"] == "ngap"


def test_enrich_preserves_raw_fields() -> None:
    rec = make_record(seq=4, mm_type=68, mm_cause=20)
    out = enrich(rec)
    # Raw tshark field retained untouched.
    assert out.fields["nas-5gs.mm.5gmm_cause"] == "20"
    # Derived field added.
    assert out.fields["mm_cause"] == 20


def test_enrich_handles_empty_record() -> None:
    rec = make_record(seq=5, frame_protocols="eth:ip")
    out = enrich(rec)
    assert out.fields["event"] is None
    assert out.fields["protocol_layer"] == "other"
    assert out.fields["mm_cause"] is None


def test_enrich_picks_tcp_ports_over_sctp() -> None:
    rec = make_record(
        seq=6,
        tcp_srcport=33333,
        tcp_dstport=7777,
        src_ip="10.0.0.1",
        dst_ip="10.0.0.2",
        frame_protocols="eth:ip:tcp:http2",
        http2_method="POST",
        http2_path="/namf-comm/v1/ue-contexts",
        http2_streamid="1",
        tcp_stream="0",
    )
    out = enrich(rec)
    assert out.fields["transport"] == "tcp"
    assert out.fields["src_port"] == 33333
    assert out.fields["dst_port"] == 7777
    assert out.fields["protocol_layer"] == "http2"


def test_enrich_sets_pfcp_msg_name() -> None:
    rec = make_record(
        seq=7, pfcp_msg_type=50, pfcp_seid="0x1", frame_protocols="eth:ip:udp:pfcp"
    )
    out = enrich(rec)
    assert out.fields["pfcp_msg_type"] == 50
    assert out.fields["pfcp_msg_name"] == "SESSION_ESTABLISHMENT_REQUEST"
    assert out.fields["protocol_layer"] == "pfcp"


def test_enrich_tolerates_comma_separated_ids() -> None:
    rec = make_record(seq=8, ran="1,2,3", amf="9,10")
    out = enrich(rec)
    assert out.fields["ran_ue_ngap_id"] == "1"
    assert out.fields["amf_ue_ngap_id"] == "9"


def test_enrich_preserves_identity() -> None:
    rec = make_record(seq=9, mm_type=65)
    out = enrich(rec)
    assert out.source == rec.source
    assert out.seq == rec.seq
    assert out.timestamp == rec.timestamp
