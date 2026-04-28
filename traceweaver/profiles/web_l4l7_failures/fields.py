"""
Tshark field catalogue + event vocabulary for the `web_l4l7_failures`
profile.

`EXTRACT_FIELDS` is the list passed to `tshark -e`. We pick the union
of fields needed to reason about DNS, TCP, TLS and WebSocket failures,
**without** relying on TLS decryption — handshake observation
(SNI / handshake type / RST mid-flight) is enough for the failure
modes this profile covers.

The `*_TO_EVENT` maps are kept as flat dicts (no Pydantic, no v1
imports) so the enricher module can import them with zero cost.

Why these specific fields?

    Each field below was chosen by inspecting one of the canonical
    pcaps under tests/fixtures/web_l4l7/pcaps/ — see the design doc
    for the field-by-field rationale.
"""

from __future__ import annotations


# ---- tshark -e -------------------------------------------------------

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
    "tcp.flags",
    "tcp.analysis.retransmission",
    "udp.srcport",
    "udp.dstport",
    "udp.stream",
    # DNS
    "dns.id",
    "dns.flags.response",
    "dns.flags.rcode",
    "dns.qry.name",
    "dns.qry.type",
    "dns.resp.name",
    # TLS handshake (no decryption needed)
    "tls.handshake.type",
    "tls.handshake.extensions_server_name",
    "tls.handshake.ciphersuite",
    "tls.handshake.extensions.supported_version",
    # TLS alert (TLS 1.2 only — TLS 1.3 encrypts post-handshake alerts)
    "tls.alert_message.level",
    "tls.alert_message.desc",
    # HTTP (used for WS upgrade and as a generic L7 anchor)
    "http.request.method",
    "http.request.uri",
    "http.response.code",
    "http.upgrade",
    # WebSocket frames
    "websocket.opcode",
    "websocket.payload_length",
)


EXTRACT_DISPLAY_FILTER: str = "dns || tcp || tls || http || websocket"


# ---- DNS rcode -> event name ----------------------------------------
# RFC 6895 standard codes only; rare codes (BADVERS etc.) collapse to
# DNS_RESPONSE_OTHER.

DNS_RCODE_TO_EVENT: dict[int, str] = {
    0: "DNS_RESPONSE_OK",
    1: "DNS_RESPONSE_FORMERR",
    2: "DNS_RESPONSE_SERVFAIL",
    3: "DNS_RESPONSE_NXDOMAIN",
    4: "DNS_RESPONSE_NOTIMP",
    5: "DNS_RESPONSE_REFUSED",
}

DNS_RCODE_NAMES: dict[int, str] = {
    0: "NOERROR",
    1: "FORMERR",
    2: "SERVFAIL",
    3: "NXDOMAIN",
    4: "NOTIMP",
    5: "REFUSED",
    6: "YXDOMAIN",
    7: "YXRRSET",
    8: "NXRRSET",
    9: "NOTAUTH",
    10: "NOTZONE",
}

# DNS qtype numbers we care about for human-readable display.
DNS_QTYPE_NAMES: dict[int, str] = {
    1: "A",
    2: "NS",
    5: "CNAME",
    6: "SOA",
    12: "PTR",
    15: "MX",
    16: "TXT",
    28: "AAAA",
    33: "SRV",
    65: "HTTPS",
}


# ---- TLS handshake type -> event name -------------------------------
# IANA TLS HandshakeType. We map the common ones; rare types
# (NewSessionTicket, EndOfEarlyData, KeyUpdate, ...) are rarely
# meaningful in failure-diagnosis contexts and collapse to
# TLS_HANDSHAKE_OTHER.

TLS_HANDSHAKE_TYPE_TO_EVENT: dict[int, str] = {
    1: "TLS_CLIENT_HELLO",
    2: "TLS_SERVER_HELLO",
    11: "TLS_CERTIFICATE",
    12: "TLS_SERVER_KEY_EXCHANGE",
    13: "TLS_CERTIFICATE_REQUEST",
    14: "TLS_SERVER_HELLO_DONE",
    15: "TLS_CERTIFICATE_VERIFY",
    16: "TLS_CLIENT_KEY_EXCHANGE",
    20: "TLS_FINISHED",
}


# ---- WebSocket opcode -> event name ---------------------------------
# RFC 6455 §5.2.

WS_OPCODE_TO_EVENT: dict[int, str] = {
    0x0: "WS_CONTINUATION",
    0x1: "WS_TEXT",
    0x2: "WS_BINARY",
    0x8: "WS_CLOSE",
    0x9: "WS_PING",
    0xA: "WS_PONG",
}


# ---- TCP flag bits --------------------------------------------------
# Used by the enricher to classify SYN / SYN+ACK / RST / FIN frames.
# We DO NOT emit an event for plain ACK or data segments — only for
# state-transition frames; otherwise the event stream becomes noise.

TCP_FLAG_FIN = 0x01
TCP_FLAG_SYN = 0x02
TCP_FLAG_RST = 0x04
TCP_FLAG_PSH = 0x08
TCP_FLAG_ACK = 0x10


__all__ = [
    "EXTRACT_FIELDS",
    "EXTRACT_DISPLAY_FILTER",
    "DNS_RCODE_TO_EVENT",
    "DNS_RCODE_NAMES",
    "DNS_QTYPE_NAMES",
    "TLS_HANDSHAKE_TYPE_TO_EVENT",
    "WS_OPCODE_TO_EVENT",
    "TCP_FLAG_FIN",
    "TCP_FLAG_SYN",
    "TCP_FLAG_RST",
    "TCP_FLAG_PSH",
    "TCP_FLAG_ACK",
]
