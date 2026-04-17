"""Shared fixtures for the Open5GS 5GC profile tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from traceweaver.core.profile import Profile
from traceweaver.core.profile.yaml_loader import load_profile_from_dir
from traceweaver.core.source import EnrichedSourceHandle, Record, SourceSpec
from traceweaver.core.source.fake import FakeSource


PROFILE_ROOT = (
    Path(__file__).resolve().parents[3] / "traceweaver" / "profiles" / "open5gs_5gc"
)


@pytest.fixture(scope="module")
def profile() -> Profile:
    return load_profile_from_dir(PROFILE_ROOT)


# ---- synthetic record builder ----------------------------------------

def make_record(
    seq: int,
    *,
    timestamp: float | None = None,
    ran: str | None = None,
    amf: str | None = None,
    mm_type: int | None = None,
    mm_cause: int | None = None,
    sm_type: int | None = None,
    sm_cause: int | None = None,
    proc: int | None = None,
    pdu_session_id: str | None = None,
    http2_method: str | None = None,
    http2_path: str | None = None,
    http2_status: str | None = None,
    http2_streamid: str | None = None,
    tcp_stream: str | None = None,
    pfcp_msg_type: int | None = None,
    pfcp_seid: str | None = None,
    pfcp_cause: str | None = None,
    src_ip: str | None = None,
    dst_ip: str | None = None,
    tcp_srcport: int | None = None,
    tcp_dstport: int | None = None,
    frame_protocols: str | None = None,
) -> Record:
    """Build a raw tshark-shaped record (pre-enrichment)."""

    fields: dict = {}
    if frame_protocols is None:
        parts = []
        if mm_type is not None or sm_type is not None:
            parts.append("nas-5gs")
        if proc is not None or mm_type is not None or sm_type is not None:
            parts.append("ngap")
        if pfcp_msg_type is not None:
            parts.append("pfcp")
        if http2_method is not None or http2_status is not None or http2_streamid is not None:
            parts.append("http2")
        if not parts:
            parts.append("eth:ip")
        frame_protocols = ":".join(parts)
    fields["frame.protocols"] = frame_protocols

    if ran is not None:
        fields["ngap.RAN_UE_NGAP_ID"] = ran
    if amf is not None:
        fields["ngap.AMF_UE_NGAP_ID"] = amf
    if pdu_session_id is not None:
        fields["nas-5gs.pdu_session_id"] = pdu_session_id
    if mm_type is not None:
        fields["nas-5gs.mm.message_type"] = str(mm_type)
    if mm_cause is not None:
        fields["nas-5gs.mm.5gmm_cause"] = str(mm_cause)
    if sm_type is not None:
        fields["nas-5gs.sm.message_type"] = str(sm_type)
    if sm_cause is not None:
        fields["nas-5gs.sm.5gsm_cause"] = str(sm_cause)
    if proc is not None:
        fields["ngap.procedureCode"] = str(proc)
    if http2_method is not None:
        fields["http2.headers.method"] = http2_method
    if http2_path is not None:
        fields["http2.headers.path"] = http2_path
    if http2_status is not None:
        fields["http2.headers.status"] = http2_status
    if http2_streamid is not None:
        fields["http2.streamid"] = http2_streamid
    if tcp_stream is not None:
        fields["tcp.stream"] = tcp_stream
    if pfcp_msg_type is not None:
        fields["pfcp.msg_type"] = str(pfcp_msg_type)
    if pfcp_seid is not None:
        fields["pfcp.seid"] = pfcp_seid
    if pfcp_cause is not None:
        fields["pfcp.cause"] = pfcp_cause
    if src_ip is not None:
        fields["ip.src"] = src_ip
    if dst_ip is not None:
        fields["ip.dst"] = dst_ip
    if tcp_srcport is not None:
        fields["tcp.srcport"] = str(tcp_srcport)
    if tcp_dstport is not None:
        fields["tcp.dstport"] = str(tcp_dstport)

    return Record(
        source="pcap",
        timestamp=timestamp if timestamp is not None else 1_700_000_000.0 + seq * 0.01,
        seq=seq,
        key=(ran or "") + "|" + (amf or ""),
        fields=fields,
    )


@pytest.fixture()
def enriched_handle():
    """Return a function that builds an EnrichedSourceHandle from raw records."""

    from traceweaver.profiles.open5gs_5gc.enrich import enrich

    def _build(records: list[Record]) -> EnrichedSourceHandle:
        inner = FakeSource().ingest(
            SourceSpec(
                kind="fake",
                uri="memory://t",
                options={"records_object": records},
            )
        )
        return EnrichedSourceHandle(inner, [enrich])

    return _build
