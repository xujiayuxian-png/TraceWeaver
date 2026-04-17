"""
Tshark field catalogue for the Open5GS 5GC profile (platform-v2 M3).

`EXTRACT_FIELDS` — the canonical field names we pass to `tshark -e`
via `PcapSource`'s `options.fields`. Modern Wireshark 4.x uses the
dashed display-filter form (`nas-5gs.*`); we keep those verbatim so
PcapSource's subprocess wiring stays trivial.

`EVENT_MM_MAP` / `EVENT_SM_MAP` / `EVENT_NGAP_MAP` — integer -> event
name, copied from v1's archived `events/identify.py` and kept dep-free
(no pydantic, no v1 imports) so the enricher module can import it.
"""

from __future__ import annotations


EXTRACT_FIELDS: tuple[str, ...] = (
    # transport / IP
    "frame.protocols",
    "ip.src",
    "ip.dst",
    "ipv6.src",
    "ipv6.dst",
    "tcp.srcport",
    "tcp.dstport",
    "tcp.stream",
    "sctp.srcport",
    "sctp.dstport",
    # NGAP
    "ngap.procedureCode",
    "ngap.RAN_UE_NGAP_ID",
    "ngap.AMF_UE_NGAP_ID",
    "ngap.pDUSessionID",
    # NAS-5GS
    "nas-5gs.mm.message_type",
    "nas-5gs.mm.5gmm_cause",
    "nas-5gs.sm.message_type",
    "nas-5gs.sm.5gsm_cause",
    "nas-5gs.pdu_session_id",
    # SBI (HTTP/2 over TCP 7777 in Open5GS)
    "http2.headers.method",
    "http2.headers.path",
    "http2.headers.status",
    "http2.headers.authority",
    "http2.streamid",
    # PFCP
    "pfcp.msg_type",
    "pfcp.seid",
    "pfcp.cause",
)


EXTRACT_DECODE_AS: tuple[str, ...] = ("tcp.port==7777,http2",)

EXTRACT_DISPLAY_FILTER: str = "ngap || nas-5gs || http2 || pfcp"


# ---- Event maps ------------------------------------------------------
# Copied from archive/v1/traceweaver/profiles/open5gs_5gc/events/identify.py
# so v2 diagnostics keep the same vocabulary users already see in docs.

EVENT_MM_MAP: dict[int, str] = {
    65: "REGISTRATION_REQUEST",
    66: "REGISTRATION_ACCEPT",
    67: "REGISTRATION_COMPLETE",
    68: "REGISTRATION_REJECT",
    69: "DEREGISTRATION_REQUEST_UE_ORIG",
    70: "DEREGISTRATION_ACCEPT_UE_ORIG",
    71: "DEREGISTRATION_REQUEST_UE_TERM",
    72: "DEREGISTRATION_ACCEPT_UE_TERM",
    76: "SERVICE_REJECT",
    86: "AUTHENTICATION_REQUEST",
    87: "AUTHENTICATION_RESPONSE",
    88: "AUTHENTICATION_RESULT",
    89: "AUTHENTICATION_FAILURE",
    90: "AUTHENTICATION_REJECT",
    93: "SECURITY_MODE_COMMAND",
    94: "SECURITY_MODE_COMPLETE",
    95: "SECURITY_MODE_REJECT",
    100: "5GMM_STATUS",
}

EVENT_SM_MAP: dict[int, str] = {
    193: "PDU_SESSION_ESTABLISHMENT_REQUEST",
    194: "PDU_SESSION_ESTABLISHMENT_ACCEPT",
    195: "PDU_SESSION_ESTABLISHMENT_REJECT",
    196: "PDU_SESSION_AUTHENTICATION_COMMAND",
    201: "PDU_SESSION_MODIFICATION_REQUEST",
    202: "PDU_SESSION_MODIFICATION_ACCEPT",
    203: "PDU_SESSION_MODIFICATION_REJECT",
    209: "PDU_SESSION_RELEASE_REQUEST",
    210: "PDU_SESSION_RELEASE_REJECT",
    211: "PDU_SESSION_RELEASE_COMMAND",
    212: "PDU_SESSION_RELEASE_COMPLETE",
    214: "5GSM_STATUS",
}

EVENT_NGAP_MAP: dict[int, str] = {
    14: "NGAP_INITIAL_CONTEXT_SETUP",
    15: "NGAP_INITIAL_UE_MESSAGE",
    29: "NGAP_PDU_SESSION_RESOURCE_SETUP",
    30: "NGAP_PDU_SESSION_RESOURCE_RELEASE",
    41: "NGAP_UE_CONTEXT_RELEASE",
    46: "NGAP_DOWNLINK_NAS_TRANSPORT",
    47: "NGAP_UPLINK_NAS_TRANSPORT",
}


# PFCP message type -> name (subset that shows up in Open5GS captures).
PFCP_MSG_MAP: dict[int, str] = {
    1: "HEARTBEAT_REQUEST",
    2: "HEARTBEAT_RESPONSE",
    5: "ASSOCIATION_SETUP_REQUEST",
    6: "ASSOCIATION_SETUP_RESPONSE",
    50: "SESSION_ESTABLISHMENT_REQUEST",
    51: "SESSION_ESTABLISHMENT_RESPONSE",
    52: "SESSION_MODIFICATION_REQUEST",
    53: "SESSION_MODIFICATION_RESPONSE",
    54: "SESSION_DELETION_REQUEST",
    55: "SESSION_DELETION_RESPONSE",
    56: "SESSION_REPORT_REQUEST",
    57: "SESSION_REPORT_RESPONSE",
}


__all__ = [
    "EVENT_MM_MAP",
    "EVENT_NGAP_MAP",
    "EVENT_SM_MAP",
    "EXTRACT_DECODE_AS",
    "EXTRACT_DISPLAY_FILTER",
    "EXTRACT_FIELDS",
    "PFCP_MSG_MAP",
]
