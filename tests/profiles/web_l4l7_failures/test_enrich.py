"""Tests for the web_l4l7_failures record enricher."""

from __future__ import annotations

from tests.profiles.web_l4l7_failures.conftest import make_record

from traceweaver.profiles.web_l4l7_failures.enrich import enrich


# ---- DNS -----------------------------------------------------------------

def test_dns_query_a_record() -> None:
    out = enrich(make_record(1, {
        "frame.protocols": "eth:ethertype:ip:udp:dns",
        "ip.src": "10.5.0.100", "ip.dst": "10.5.0.10",
        "dns.id": "12345",
        "dns.flags.response": "0",
        "dns.qry.name": "server.local",
        "dns.qry.type": "1",
    }))
    assert out.fields["event"] == "DNS_QUERY"
    assert out.fields["protocol_layer"] == "dns"
    assert out.fields["dns_qname"] == "server.local"
    assert out.fields["dns_qtype"] == 1
    assert out.fields["dns_qtype_name"] == "A"
    assert out.fields["flow_id"] == "dns:12345"
    assert out.fields["dns_is_response"] is False


def test_dns_response_ok() -> None:
    out = enrich(make_record(2, {
        "frame.protocols": "eth:ethertype:ip:udp:dns",
        "dns.id": "12345",
        "dns.flags.response": "1",
        "dns.flags.rcode": "0",
        "dns.qry.name": "server.local",
        "dns.qry.type": "1",
    }))
    assert out.fields["event"] == "DNS_RESPONSE_OK"
    assert out.fields["dns_rcode"] == 0
    assert out.fields["dns_rcode_name"] == "NOERROR"


def test_dns_response_nxdomain() -> None:
    out = enrich(make_record(3, {
        "frame.protocols": "eth:ethertype:ip:udp:dns",
        "dns.id": "999",
        "dns.flags.response": "1",
        "dns.flags.rcode": "3",
        "dns.qry.name": "does-not-exist.local",
        "dns.qry.type": "1",
    }))
    assert out.fields["event"] == "DNS_RESPONSE_NXDOMAIN"
    assert out.fields["dns_rcode_name"] == "NXDOMAIN"


def test_dns_response_servfail() -> None:
    out = enrich(make_record(4, {
        "frame.protocols": "eth:ip:udp:dns",
        "dns.id": "1", "dns.flags.response": "1", "dns.flags.rcode": "2",
    }))
    assert out.fields["event"] == "DNS_RESPONSE_SERVFAIL"


def test_dns_response_with_tshark_true_false_literals() -> None:
    """tshark's `-T fields` renders `dns.flags.response` as the literal
    strings 'True'/'False', not '1'/'0'. The enricher must handle both
    -- regression test for an early version that only accepted ints."""
    out_query = enrich(make_record(6, {
        "frame.protocols": "eth:ip:udp:dns",
        "dns.id": "0xccd9",   # tshark also renders dns.id in hex
        "dns.flags.response": "False",
        "dns.qry.name": "x.local",
        "dns.qry.type": "1",
    }))
    assert out_query.fields["event"] == "DNS_QUERY"
    assert out_query.fields["dns_id"] == 0xCCD9
    assert out_query.fields["dns_is_response"] is False
    assert out_query.fields["flow_id"] == "dns:52441"

    out_resp = enrich(make_record(7, {
        "frame.protocols": "eth:ip:udp:dns",
        "dns.id": "0xccd9",
        "dns.flags.response": "True",
        "dns.flags.rcode": "3",
        "dns.qry.name": "x.local",
        "dns.qry.type": "1",
    }))
    assert out_resp.fields["event"] == "DNS_RESPONSE_NXDOMAIN"
    assert out_resp.fields["dns_is_response"] is True


def test_dns_aaaa_query_separate_qtype() -> None:
    """Linux glibc resolver fires A and AAAA queries; we should keep
    them as distinct events with the right qtype label."""
    out = enrich(make_record(5, {
        "frame.protocols": "eth:ip:udp:dns",
        "dns.id": "12346", "dns.flags.response": "0",
        "dns.qry.name": "server.local", "dns.qry.type": "28",
    }))
    assert out.fields["event"] == "DNS_QUERY"
    assert out.fields["dns_qtype_name"] == "AAAA"


# ---- TCP -----------------------------------------------------------------

def test_tcp_syn() -> None:
    out = enrich(make_record(10, {
        "frame.protocols": "eth:ethertype:ip:tcp",
        "ip.src": "10.5.0.100", "ip.dst": "10.5.0.20",
        "tcp.srcport": "55844", "tcp.dstport": "443",
        "tcp.stream": "0", "tcp.flags": "0x0002",
    }))
    assert out.fields["event"] == "TCP_SYN"
    assert out.fields["protocol_layer"] == "tcp"
    assert out.fields["tcp_flag_names"] == ["SYN"]
    assert out.fields["flow_id"] == "tcp:0"
    assert out.fields["transport"] == "tcp"


def test_tcp_syn_ack() -> None:
    out = enrich(make_record(11, {
        "frame.protocols": "eth:ip:tcp",
        "tcp.flags": "0x0012", "tcp.stream": "0",
    }))
    assert out.fields["event"] == "TCP_SYN_ACK"
    assert set(out.fields["tcp_flag_names"]) == {"SYN", "ACK"}


def test_tcp_rst() -> None:
    """RST + ACK frame (0x0014) should classify as TCP_RST regardless of ACK bit."""
    out = enrich(make_record(12, {
        "frame.protocols": "eth:ip:tcp",
        "tcp.flags": "0x0014", "tcp.stream": "1",
    }))
    assert out.fields["event"] == "TCP_RST"
    assert "RST" in out.fields["tcp_flag_names"]


def test_tcp_pure_ack_has_no_event() -> None:
    """Plain ACK frames (no SYN/FIN/RST) carry no event — keeps the
    event stream signal-dense."""
    out = enrich(make_record(13, {
        "frame.protocols": "eth:ip:tcp",
        "tcp.flags": "0x0010", "tcp.stream": "0",
    }))
    assert out.fields["event"] is None
    assert out.fields["tcp_flag_names"] == ["ACK"]
    assert out.fields["protocol_layer"] == "tcp"


def test_tcp_fin() -> None:
    out = enrich(make_record(14, {
        "frame.protocols": "eth:ip:tcp",
        "tcp.flags": "0x0011",   # FIN+ACK
        "tcp.stream": "0",
    }))
    assert out.fields["event"] == "TCP_FIN"


def test_tcp_retransmit_flag_propagated() -> None:
    out = enrich(make_record(15, {
        "frame.protocols": "eth:ip:tcp",
        "tcp.flags": "0x0010", "tcp.stream": "0",
        "tcp.analysis.retransmission": "1",
    }))
    assert out.fields["is_retransmit"] is True


# ---- TLS -----------------------------------------------------------------

def test_tls_client_hello_with_sni() -> None:
    out = enrich(make_record(20, {
        "frame.protocols": "eth:ip:tcp:tls",
        "tcp.stream": "0",
        "tls.handshake.type": "1",
        "tls.handshake.extensions_server_name": "server.local",
    }))
    assert out.fields["event"] == "TLS_CLIENT_HELLO"
    assert out.fields["protocol_layer"] == "tls"
    assert out.fields["tls_sni"] == "server.local"


def test_tls_server_hello_when_multiple_handshake_types_in_frame() -> None:
    """A TLS record may bundle ServerHello + Certificate + ServerHelloDone;
    tshark renders this as a comma-joined `tls.handshake.type` cell.
    Take the first occurrence."""
    out = enrich(make_record(21, {
        "frame.protocols": "eth:ip:tcp:tls",
        "tcp.stream": "0",
        "tls.handshake.type": "2,11,14",
    }))
    assert out.fields["event"] == "TLS_SERVER_HELLO"
    assert out.fields["tls_handshake_type"] == 2


def test_tls_alert_takes_priority_over_handshake() -> None:
    """If tshark surfaces a plaintext Alert (TLS 1.2), surface that as
    the event rather than any concurrent handshake type."""
    out = enrich(make_record(22, {
        "frame.protocols": "eth:ip:tcp:tls",
        "tls.alert_message.level": "fatal",
        "tls.alert_message.desc": "Certificate Expired",
    }))
    assert out.fields["event"] == "TLS_ALERT"
    assert out.fields["tls_alert_level"] == "fatal"
    assert out.fields["tls_alert_desc"] == "Certificate Expired"


# ---- WebSocket -----------------------------------------------------------

def test_websocket_close_frame() -> None:
    out = enrich(make_record(30, {
        "frame.protocols": "eth:ip:tcp:http:websocket",
        "tcp.stream": "0",
        "websocket.opcode": "8",
    }))
    assert out.fields["event"] == "WS_CLOSE"
    assert out.fields["protocol_layer"] == "websocket"
    assert out.fields["ws_opcode_name"] == "CLOSE"


def test_websocket_text_frame() -> None:
    out = enrich(make_record(31, {
        "frame.protocols": "eth:ip:tcp:http:websocket",
        "websocket.opcode": "1",
    }))
    assert out.fields["event"] == "WS_TEXT"


# ---- HTTP / WS upgrade ---------------------------------------------------

def test_http_websocket_upgrade_request() -> None:
    out = enrich(make_record(40, {
        "frame.protocols": "eth:ip:tcp:http",
        "http.request.method": "GET",
        "http.request.uri": "/",
        "http.upgrade": "websocket",
    }))
    assert out.fields["event"] == "WS_HANDSHAKE_REQUEST"
    assert out.fields["protocol_layer"] == "http"


def test_http_websocket_upgrade_response_101() -> None:
    out = enrich(make_record(41, {
        "frame.protocols": "eth:ip:tcp:http",
        "http.response.code": "101",
    }))
    assert out.fields["event"] == "WS_HANDSHAKE_RESPONSE_OK"


# ---- noise frames --------------------------------------------------------

def test_arp_frame_classified_as_arp_with_no_event() -> None:
    out = enrich(make_record(50, {"frame.protocols": "eth:ethertype:arp"}))
    assert out.fields["event"] is None
    assert out.fields["protocol_layer"] == "arp"
    assert out.fields["flow_id"] is None


def test_icmpv6_frame_classified_as_icmp() -> None:
    out = enrich(make_record(51, {"frame.protocols": "eth:ethertype:ipv6:icmpv6"}))
    assert out.fields["protocol_layer"] == "icmp"
    assert out.fields["event"] is None


# ---- contract: raw fields preserved --------------------------------------

def test_raw_fields_are_preserved() -> None:
    raw = {
        "frame.protocols": "eth:ip:tcp",
        "tcp.flags": "0x0002",
        "tcp.stream": "5",
        "ip.src": "10.5.0.100",
    }
    out = enrich(make_record(60, raw))
    for k, v in raw.items():
        assert out.fields[k] == v
    # Derived field added.
    assert out.fields["event"] == "TCP_SYN"


# ---- contract: profile loads -------------------------------------------

def test_profile_yaml_loads_cleanly(profile) -> None:
    """Smoke check: profile.yaml + enrichers reference resolves.
    Tools / prompts / knowledge are loaded lazily so this passes even
    while those files are still being written."""
    assert profile.name == "web_l4l7_failures"
    assert "pcap" in profile.applies_to_sources
