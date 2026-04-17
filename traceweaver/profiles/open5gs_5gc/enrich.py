"""
Record enricher for the Open5GS 5GC profile.

Translates the raw tshark columns that `PcapSource` yields into the
semantic fields the profile's tools and the LLM actually reason about:

    event              : high-level name (e.g. REGISTRATION_REJECT)
    protocol_layer     : nas_5gmm | nas_5gsm | ngap | http2 | pfcp | other
    src_ip / dst_ip    : IPv4 if present, else IPv6
    src_port / dst_port: transport ports normalized across tcp / sctp
    ran_ue_ngap_id     : string or None
    amf_ue_ngap_id     : string or None
    pdu_session_id     : string or None
    mm_cause           : integer or None
    sm_cause           : integer or None
    nas_mm_type        : integer or None
    nas_sm_type        : integer or None

The enricher NEVER removes raw tshark fields. Tools and the LLM can
still inspect `frame.protocols`, `http2.headers.path`, etc. directly.
"""

from __future__ import annotations

from typing import Any

from traceweaver.core.source import Record
from traceweaver.profiles.open5gs_5gc.fields import (
    EVENT_MM_MAP,
    EVENT_NGAP_MAP,
    EVENT_SM_MAP,
    PFCP_MSG_MAP,
)


# ---- parsers ---------------------------------------------------------

def _parse_int(raw: Any) -> int | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    # tshark emits some numeric fields with a "0x" prefix or as a
    # comma-separated list (first occurrence only thanks to -E occurrence=f).
    try:
        return int(text, 0)
    except ValueError:
        return None


def _primary(raw: Any) -> str | None:
    """Return the first non-empty token of a possibly comma-joined value."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    for sep in (",", "|"):
        if sep in text:
            text = text.split(sep, 1)[0].strip()
            if text:
                return text
    return text


def _protocol_layer(frame_protocols: str, mm: int | None, sm: int | None) -> str:
    protos = frame_protocols or ""
    # NAS wins over NGAP (the NAS PDU is carried inside NGAP but its
    # semantics drive the LLM's reasoning first).
    if mm is not None:
        return "nas_5gmm"
    if sm is not None:
        return "nas_5gsm"
    if "ngap" in protos:
        return "ngap"
    if "http2" in protos:
        return "http2"
    if "pfcp" in protos:
        return "pfcp"
    if "sctp" in protos:
        return "sctp"
    return "other"


def _event_name(
    mm: int | None,
    sm: int | None,
    proc: int | None,
    frame_protocols: str,
) -> str | None:
    if mm is not None and mm in EVENT_MM_MAP:
        return EVENT_MM_MAP[mm]
    if sm is not None and sm in EVENT_SM_MAP:
        return EVENT_SM_MAP[sm]
    if "ngap" in (frame_protocols or "") and proc is not None and proc in EVENT_NGAP_MAP:
        return EVENT_NGAP_MAP[proc]
    return None


# ---- the enricher ----------------------------------------------------

def enrich(record: Record) -> Record:
    """Add derived fields to `record`; raw fields are preserved."""

    f = record.fields

    mm = _parse_int(f.get("nas-5gs.mm.message_type"))
    sm = _parse_int(f.get("nas-5gs.sm.message_type"))
    proc = _parse_int(f.get("ngap.procedureCode"))
    mm_cause = _parse_int(f.get("nas-5gs.mm.5gmm_cause"))
    sm_cause = _parse_int(f.get("nas-5gs.sm.5gsm_cause"))

    frame_protocols = str(f.get("frame.protocols", "") or "")
    event = _event_name(mm, sm, proc, frame_protocols)
    layer = _protocol_layer(frame_protocols, mm, sm)

    src_ip = _primary(f.get("ip.src")) or _primary(f.get("ipv6.src"))
    dst_ip = _primary(f.get("ip.dst")) or _primary(f.get("ipv6.dst"))

    tcp_src = _parse_int(f.get("tcp.srcport"))
    tcp_dst = _parse_int(f.get("tcp.dstport"))
    sctp_src = _parse_int(f.get("sctp.srcport"))
    sctp_dst = _parse_int(f.get("sctp.dstport"))

    if tcp_src is not None or tcp_dst is not None:
        src_port, dst_port, transport = tcp_src, tcp_dst, "tcp"
    elif sctp_src is not None or sctp_dst is not None:
        src_port, dst_port, transport = sctp_src, sctp_dst, "sctp"
    else:
        src_port, dst_port, transport = None, None, None

    pfcp_msg_type = _parse_int(f.get("pfcp.msg_type"))
    pfcp_name = PFCP_MSG_MAP.get(pfcp_msg_type) if pfcp_msg_type is not None else None

    derived: dict[str, Any] = {
        "event": event,
        "protocol_layer": layer,
        "src_ip": src_ip,
        "dst_ip": dst_ip,
        "src_port": src_port,
        "dst_port": dst_port,
        "transport": transport,
        "ran_ue_ngap_id": _primary(f.get("ngap.RAN_UE_NGAP_ID")),
        "amf_ue_ngap_id": _primary(f.get("ngap.AMF_UE_NGAP_ID")),
        "pdu_session_id": _primary(f.get("nas-5gs.pdu_session_id"))
        or _primary(f.get("ngap.pDUSessionID")),
        "mm_cause": mm_cause,
        "sm_cause": sm_cause,
        "nas_mm_type": mm,
        "nas_sm_type": sm,
        "ngap_procedure_code": proc,
        "pfcp_msg_type": pfcp_msg_type,
        "pfcp_msg_name": pfcp_name,
    }

    merged = dict(f)
    for key, val in derived.items():
        # Don't clobber a raw field that happens to share a name; raw
        # data wins, derived data loses, so users can always grep the
        # original. (None of the `derived` keys collide today, but
        # defensive coding keeps future additions safe.)
        merged.setdefault(key, val)

    return record.model_copy(update={"fields": merged})


__all__ = ["enrich"]
