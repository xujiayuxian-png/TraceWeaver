"""
Record enricher for the `web_l4l7_failures` profile.

Per-frame, stateless: each `Record` is enriched independently of its
neighbours. State-dependent observations (TCP_HANDSHAKE_DONE,
TLS_HANDSHAKE_FAILED, WS_CONNECTION_DROPPED) are deliberately deferred
to the tool layer where they can join across the whole capture.

This keeps `enrich` O(1) per frame and matches the contract the
`open5gs_5gc` profile already follows. Profile-internal style
consistency is a deliberate non-goal of `core/`; it's a deliberate
goal **here**.

Derived fields produced:

    event              : high-level event name (e.g. TCP_RST,
                         DNS_RESPONSE_NXDOMAIN), or None for noise frames
    protocol_layer     : dns | tcp | tls | websocket | http | other
    src_ip / dst_ip    : IPv4 first, IPv6 fallback
    src_port / dst_port: from tcp.* if present, else udp.*
    transport          : tcp | udp | None
    flow_id            : (`tcp:<stream>` | `udp:<stream>` | `dns:<id>`) — None for ARP/ICMP
    dns_id             : int or None
    dns_qname          : string or None
    dns_qtype          : int or None
    dns_qtype_name     : "A" / "AAAA" / "CNAME" / ... or None
    dns_rcode          : int or None
    dns_rcode_name     : "NXDOMAIN" / "SERVFAIL" / ... or None
    tls_handshake_type : int or None (first if multiple in same record)
    tls_sni            : SNI from ClientHello, or None
    tls_alert_level    : "warning" / "fatal" / None  (TLS ≤1.2 only)
    tls_alert_desc     : alert description string, or None
    ws_opcode          : int or None
    ws_opcode_name     : human label like "TEXT", "CLOSE"
    tcp_stream         : int or None
    tcp_flags_int      : int or None (parsed from "0x0014")
    tcp_flag_names     : sorted list[str]  e.g. ["RST", "ACK"]
    is_retransmit      : bool

Raw tshark fields are NEVER stripped; tools and the LLM can still
inspect `frame.protocols`, `tls.handshake.ciphersuite`, etc. directly.
"""

from __future__ import annotations

from typing import Any

from traceweaver.core.source import Record
from traceweaver.profiles.web_l4l7_failures.fields import (
    DNS_QTYPE_NAMES,
    DNS_RCODE_NAMES,
    DNS_RCODE_TO_EVENT,
    TCP_FLAG_ACK,
    TCP_FLAG_FIN,
    TCP_FLAG_RST,
    TCP_FLAG_SYN,
    TLS_HANDSHAKE_TYPE_TO_EVENT,
    WS_OPCODE_TO_EVENT,
)


# ---- low-level parsers ---------------------------------------------------

def _parse_int(raw: Any) -> int | None:
    """Parse a tshark cell into an int. Accepts decimal, 0x-prefixed,
    or comma-joined (first token wins). Empty -> None."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    # tshark may emit comma-joined when the same field appears multiple
    # times in one frame (e.g. tls.handshake.type for ServerHello + Cert
    # bundled into a single record). We take the first occurrence — the
    # rest is information the tool layer can recover via raw fields.
    if "," in text:
        text = text.split(",", 1)[0].strip()
        if not text:
            return None
    try:
        return int(text, 0)
    except ValueError:
        return None


def _primary(raw: Any) -> str | None:
    """First non-empty token of a comma-joined cell, or None."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if "," in text:
        text = text.split(",", 1)[0].strip()
        return text or None
    return text


def _parse_bool_flag(raw: Any) -> bool:
    """tshark emits expert-info flags like `tcp.analysis.retransmission`
    as '1' (set) or '' (unset). Empty / None / '0' = False."""
    if raw is None:
        return False
    text = str(raw).strip()
    return text not in ("", "0")


def _parse_bool_tshark(raw: Any) -> bool | None:
    """tshark's `-T fields` renders boolean *value* fields (like
    `dns.flags.response`) as the literal strings 'True' / 'False',
    NOT as numeric '1' / '0'. Treats them both ways for safety, plus
    returns None for empty cells so callers can distinguish "absent"
    from "False"."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    lower = text.lower()
    if lower in ("1", "true"):
        return True
    if lower in ("0", "false"):
        return False
    return None


# ---- TCP flag classification ---------------------------------------------

_TCP_FLAG_NAMES: tuple[tuple[int, str], ...] = (
    (TCP_FLAG_FIN, "FIN"),
    (TCP_FLAG_SYN, "SYN"),
    (TCP_FLAG_RST, "RST"),
    (TCP_FLAG_ACK, "ACK"),
)


def _tcp_flag_names(flags_int: int | None) -> list[str]:
    if flags_int is None:
        return []
    return [name for bit, name in _TCP_FLAG_NAMES if flags_int & bit]


def _tcp_event(flag_names: list[str]) -> str | None:
    """Classify a TCP frame by its flag set.

    Only state-transition frames produce an event:
      RST   -> TCP_RST                 (regardless of ACK bit)
      SYN+ACK -> TCP_SYN_ACK
      SYN   -> TCP_SYN
      FIN   -> TCP_FIN                 (regardless of ACK bit)
    Everything else (plain ACK, data segments) returns None to keep the
    event stream signal-dense.
    """
    flags = set(flag_names)
    if "RST" in flags:
        return "TCP_RST"
    if "SYN" in flags and "ACK" in flags:
        return "TCP_SYN_ACK"
    if "SYN" in flags:
        return "TCP_SYN"
    if "FIN" in flags:
        return "TCP_FIN"
    return None


# ---- protocol layer & event decision tree ------------------------------

def _protocol_layer(
    frame_protocols: str,
    *,
    has_dns: bool,
    has_tls: bool,
    has_ws: bool,
    has_http: bool,
    has_tcp: bool,
    has_udp: bool,
) -> str:
    # Order matters: most specific (highest L7) wins. WS and TLS are
    # both above TCP; HTTP above TCP; DNS above UDP; etc.
    if has_ws:
        return "websocket"
    if has_tls:
        return "tls"
    if has_http:
        return "http"
    if has_dns:
        return "dns"
    if has_tcp:
        return "tcp"
    if has_udp:
        return "udp"
    if "arp" in frame_protocols:
        return "arp"
    if "icmp" in frame_protocols:
        return "icmp"
    return "other"


def _dns_event(
    *,
    is_response: bool | None,
    rcode: int | None,
) -> str | None:
    if is_response is False:
        return "DNS_QUERY"
    if is_response is True:
        if rcode is not None and rcode in DNS_RCODE_TO_EVENT:
            return DNS_RCODE_TO_EVENT[rcode]
        return "DNS_RESPONSE_OTHER"
    return None


def _tls_event(
    *,
    handshake_type: int | None,
    alert_desc: str | None,
) -> str | None:
    # An Alert is more "interesting" than a HandshakeType in the same
    # frame (TLS 1.2 servers can send Alert+CCS together), so check it
    # first. TLS 1.3 encrypts alerts so this branch only hits TLS 1.2.
    if alert_desc:
        return "TLS_ALERT"
    if handshake_type is not None and handshake_type in TLS_HANDSHAKE_TYPE_TO_EVENT:
        return TLS_HANDSHAKE_TYPE_TO_EVENT[handshake_type]
    if handshake_type is not None:
        return "TLS_HANDSHAKE_OTHER"
    return None


def _ws_event(opcode: int | None) -> str | None:
    if opcode is None:
        return None
    if opcode in WS_OPCODE_TO_EVENT:
        return WS_OPCODE_TO_EVENT[opcode]
    return "WS_OPCODE_OTHER"


def _http_event(method: str | None, response_code: int | None, upgrade: str | None) -> str | None:
    if response_code == 101:
        return "WS_HANDSHAKE_RESPONSE_OK"
    if upgrade and "websocket" in upgrade.lower() and method is not None:
        return "WS_HANDSHAKE_REQUEST"
    if response_code is not None and 400 <= response_code < 600 and method is None:
        # request method is empty on response frames; keep this loose.
        return "HTTP_RESPONSE_ERROR"
    return None


# ---- the enricher --------------------------------------------------------

def enrich(record: Record) -> Record:
    """Add derived fields to `record`; raw fields are preserved."""

    f = record.fields

    # raw lookups
    frame_protocols = str(f.get("frame.protocols", "") or "")

    dns_id = _parse_int(f.get("dns.id"))
    is_response = _parse_bool_tshark(f.get("dns.flags.response"))
    dns_rcode = _parse_int(f.get("dns.flags.rcode"))
    dns_qname = _primary(f.get("dns.qry.name"))
    dns_qtype = _parse_int(f.get("dns.qry.type"))

    tls_handshake_type = _parse_int(f.get("tls.handshake.type"))
    tls_sni = _primary(f.get("tls.handshake.extensions_server_name"))
    tls_alert_level = _primary(f.get("tls.alert_message.level"))
    tls_alert_desc = _primary(f.get("tls.alert_message.desc"))

    ws_opcode = _parse_int(f.get("websocket.opcode"))

    http_method = _primary(f.get("http.request.method"))
    http_response_code = _parse_int(f.get("http.response.code"))
    http_upgrade = _primary(f.get("http.upgrade"))

    tcp_stream = _parse_int(f.get("tcp.stream"))
    udp_stream = _parse_int(f.get("udp.stream"))
    tcp_flags_int = _parse_int(f.get("tcp.flags"))
    tcp_flag_names = _tcp_flag_names(tcp_flags_int)
    is_retransmit = _parse_bool_flag(f.get("tcp.analysis.retransmission"))

    # IP / port normalization
    src_ip = _primary(f.get("ip.src")) or _primary(f.get("ipv6.src"))
    dst_ip = _primary(f.get("ip.dst")) or _primary(f.get("ipv6.dst"))
    tcp_src = _parse_int(f.get("tcp.srcport"))
    tcp_dst = _parse_int(f.get("tcp.dstport"))
    udp_src = _parse_int(f.get("udp.srcport"))
    udp_dst = _parse_int(f.get("udp.dstport"))
    if tcp_src is not None or tcp_dst is not None:
        src_port, dst_port, transport = tcp_src, tcp_dst, "tcp"
    elif udp_src is not None or udp_dst is not None:
        src_port, dst_port, transport = udp_src, udp_dst, "udp"
    else:
        src_port, dst_port, transport = None, None, None

    # protocol membership flags (cheap substring tests on frame.protocols)
    has_tcp = "tcp" in frame_protocols
    has_udp = "udp" in frame_protocols
    has_dns = (dns_id is not None) or "dns" in frame_protocols
    has_tls = (tls_handshake_type is not None) or (tls_alert_desc is not None) or "tls" in frame_protocols
    has_ws = (ws_opcode is not None) or "websocket" in frame_protocols
    has_http = (http_method is not None) or (http_response_code is not None) or "http" in frame_protocols

    layer = _protocol_layer(
        frame_protocols,
        has_dns=has_dns,
        has_tls=has_tls,
        has_ws=has_ws,
        has_http=has_http,
        has_tcp=has_tcp,
        has_udp=has_udp,
    )

    # event decision tree — most specific wins.
    event: str | None = None
    if has_ws:
        event = _ws_event(ws_opcode)
    if event is None and has_tls:
        event = _tls_event(handshake_type=tls_handshake_type, alert_desc=tls_alert_desc)
    if event is None and has_http:
        event = _http_event(http_method, http_response_code, http_upgrade)
    if event is None and has_dns:
        event = _dns_event(is_response=is_response, rcode=dns_rcode)
    if event is None and has_tcp:
        event = _tcp_event(tcp_flag_names)

    # flow id — used by list_flows / get_flow_timeline tools.
    if dns_id is not None:
        flow_id = f"dns:{dns_id}"
    elif tcp_stream is not None:
        flow_id = f"tcp:{tcp_stream}"
    elif udp_stream is not None:
        flow_id = f"udp:{udp_stream}"
    else:
        flow_id = None

    derived: dict[str, Any] = {
        "event": event,
        "protocol_layer": layer,
        "src_ip": src_ip,
        "dst_ip": dst_ip,
        "src_port": src_port,
        "dst_port": dst_port,
        "transport": transport,
        "flow_id": flow_id,
        # DNS
        "dns_id": dns_id,
        "dns_qname": dns_qname,
        "dns_qtype": dns_qtype,
        "dns_qtype_name": DNS_QTYPE_NAMES.get(dns_qtype) if dns_qtype is not None else None,
        "dns_rcode": dns_rcode,
        "dns_rcode_name": DNS_RCODE_NAMES.get(dns_rcode) if dns_rcode is not None else None,
        "dns_is_response": is_response,
        # TLS
        "tls_handshake_type": tls_handshake_type,
        "tls_sni": tls_sni,
        "tls_alert_level": tls_alert_level,
        "tls_alert_desc": tls_alert_desc,
        # WebSocket
        "ws_opcode": ws_opcode,
        "ws_opcode_name": (
            WS_OPCODE_TO_EVENT.get(ws_opcode, "").removeprefix("WS_") or None
            if ws_opcode is not None else None
        ),
        # HTTP
        "http_method": http_method,
        "http_response_code": http_response_code,
        "http_upgrade": http_upgrade,
        # TCP
        "tcp_stream": tcp_stream,
        "udp_stream": udp_stream,
        "tcp_flags_int": tcp_flags_int,
        "tcp_flag_names": tcp_flag_names,
        "is_retransmit": is_retransmit,
    }

    merged = dict(f)
    for key, val in derived.items():
        # Raw tshark fields win on collision so users can always grep
        # the original. None of `derived`'s keys collide today; this
        # is defensive for future field additions.
        merged.setdefault(key, val)

    return record.model_copy(update={"fields": merged})


__all__ = ["enrich"]
