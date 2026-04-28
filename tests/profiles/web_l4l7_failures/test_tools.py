"""Tests for the web_l4l7_failures profile tools.

These exercise the tools end-to-end against synthetic enriched records
(no real pcaps required, no tshark needed). The smoke script
`scripts/smoke_web_l4l7_profile.py` covers the real-pcap path.
"""

from __future__ import annotations

from typing import Any

import pytest

from traceweaver.core.protocols import ToolContext
from traceweaver.profiles.web_l4l7_failures.enrich import enrich
from traceweaver.profiles.web_l4l7_failures.tools.get_dns_queries import (
    GetDNSQueriesTool,
)
from traceweaver.profiles.web_l4l7_failures.tools.get_flow_timeline import (
    GetFlowTimelineTool,
)
from traceweaver.profiles.web_l4l7_failures.tools.get_records_around import (
    GetRecordsAroundTool,
)
from traceweaver.profiles.web_l4l7_failures.tools.get_tls_handshakes import (
    GetTLSHandshakesTool,
)
from traceweaver.profiles.web_l4l7_failures.tools.list_flows import ListFlowsTool
from traceweaver.profiles.web_l4l7_failures.tools.summarize_capture import (
    SummarizeCaptureTool,
)

from tests.profiles.web_l4l7_failures.conftest import make_record


# ---- helpers --------------------------------------------------------------

def _enrich_all(records):
    return [enrich(r) for r in records]


class _MemoryHandle:
    """Minimal SourceHandle stand-in: hands out enriched records."""

    def __init__(self, enriched):
        self._enriched = list(enriched)

    def iter_records(self):
        return iter(self._enriched)


def _make_dns_pair(seq_q: int, seq_r: int, dns_id: str, qname: str, qtype: str, rcode: str | None):
    """Synthetic DNS query + response pair (similar to what tshark emits)."""
    q = make_record(seq_q, {
        "frame.protocols": "eth:ip:udp:dns",
        "ip.src": "10.5.0.100", "ip.dst": "10.5.0.10",
        "dns.id": dns_id,
        "dns.flags.response": "False",
        "dns.qry.name": qname,
        "dns.qry.type": qtype,
    })
    response_fields = {
        "frame.protocols": "eth:ip:udp:dns",
        "ip.src": "10.5.0.10", "ip.dst": "10.5.0.100",
        "dns.id": dns_id,
        "dns.flags.response": "True",
        "dns.qry.name": qname,
        "dns.qry.type": qtype,
    }
    if rcode is not None:
        response_fields["dns.flags.rcode"] = rcode
    r = make_record(seq_r, response_fields)
    return [q, r]


def _make_tcp_handshake(stream: str, *, base_seq: int):
    return [
        make_record(base_seq, {
            "frame.protocols": "eth:ip:tcp",
            "tcp.flags": "0x0002", "tcp.stream": stream,
            "tcp.srcport": "55844", "tcp.dstport": "443",
            "ip.src": "10.5.0.100", "ip.dst": "10.5.0.20",
        }),
        make_record(base_seq + 1, {
            "frame.protocols": "eth:ip:tcp",
            "tcp.flags": "0x0012", "tcp.stream": stream,
            "tcp.srcport": "443", "tcp.dstport": "55844",
            "ip.src": "10.5.0.20", "ip.dst": "10.5.0.100",
        }),
    ]


def _make_handle(records):
    return _MemoryHandle(_enrich_all(records))


def _ctx(handle):
    return ToolContext(source_handle=handle)


# ---- summarize_capture ----------------------------------------------------

def test_summarize_capture_returns_three_keys() -> None:
    handle = _make_handle(_make_dns_pair(1, 2, "0xaa", "x.local", "1", "0"))
    out = SummarizeCaptureTool().run(_ctx(handle))
    assert set(out.data) >= {"event_inventory", "flow_overview", "capture_signals"}


def test_summarize_capture_signals_count_dns_nxdomain() -> None:
    records = (
        _make_dns_pair(1, 2, "0xaa", "x.local", "1", "3")
        + _make_dns_pair(3, 4, "0xbb", "y.local", "1", "3")
        + _make_dns_pair(5, 6, "0xcc", "z.local", "1", "0")
    )
    handle = _make_handle(records)
    out = SummarizeCaptureTool().run(_ctx(handle))
    sig = out.data["capture_signals"]
    assert sig["dns_query_count"] == 3
    assert sig["dns_response_count"] == 3
    assert sig["dns_nxdomain_count"] == 2
    assert sig["dns_rcode_mix"] == {"NXDOMAIN": 2, "NOERROR": 1}


def test_summarize_capture_signals_count_tcp_rst() -> None:
    records = _make_tcp_handshake("0", base_seq=1) + [
        make_record(3, {
            "frame.protocols": "eth:ip:tcp",
            "tcp.flags": "0x0014", "tcp.stream": "0",
        })
    ]
    handle = _make_handle(records)
    out = SummarizeCaptureTool().run(_ctx(handle))
    sig = out.data["capture_signals"]
    assert sig["tcp_rst_count"] == 1
    assert sig["tcp_syn_count"] == 1
    assert sig["tcp_syn_ack_count"] == 1


def test_summarize_capture_signals_tls_completed_likely_tls13() -> None:
    """A healthy TLS 1.3 connection (CH + SH, no failure) must be
    counted as completed, not failed — Finished is encrypted on TLS 1.3,
    so its absence on the wire is normal."""
    records = _make_tcp_handshake("0", base_seq=1) + [
        make_record(3, {
            "frame.protocols": "eth:ip:tcp:tls", "tcp.stream": "0",
            "tls.handshake.type": "1",
            "tls.handshake.extensions_server_name": "host.local",
        }),
        make_record(4, {
            "frame.protocols": "eth:ip:tcp:tls", "tcp.stream": "0",
            "tls.handshake.type": "2",
        }),
    ]
    handle = _make_handle(records)
    sig = SummarizeCaptureTool().run(_ctx(handle)).data["capture_signals"]
    assert sig["tls_handshake_started_count"] == 1
    assert sig["tls_handshake_completed_count"] == 1
    assert sig["tls_handshake_failed_count"] == 0


def test_summarize_capture_signals_tls_rst_mid_handshake_is_failed() -> None:
    """RST after ClientHello + ServerHello → counts as failed."""
    records = _make_tcp_handshake("0", base_seq=1) + [
        make_record(3, {
            "frame.protocols": "eth:ip:tcp:tls", "tcp.stream": "0",
            "tls.handshake.type": "1",
        }),
        make_record(4, {
            "frame.protocols": "eth:ip:tcp:tls", "tcp.stream": "0",
            "tls.handshake.type": "2",
        }),
        make_record(5, {
            "frame.protocols": "eth:ip:tcp",
            "tcp.flags": "0x0014", "tcp.stream": "0",
        }),
    ]
    handle = _make_handle(records)
    sig = SummarizeCaptureTool().run(_ctx(handle)).data["capture_signals"]
    assert sig["tls_handshake_started_count"] == 1
    assert sig["tls_handshake_completed_count"] == 0
    assert sig["tls_handshake_failed_count"] == 1


def test_summarize_capture_no_source_handle() -> None:
    out = SummarizeCaptureTool().run(ToolContext(source_handle=None))
    assert out.data["hint"] == "no source_handle"


# ---- list_flows -----------------------------------------------------------

def test_list_flows_groups_by_flow_id() -> None:
    records = (
        _make_dns_pair(1, 2, "0xaa", "x.local", "1", "0")
        + _make_tcp_handshake("0", base_seq=3)
    )
    handle = _make_handle(records)
    out = ListFlowsTool().run(_ctx(handle))
    flow_ids = [f["flow_id"] for f in out.data["flows"]]
    assert "dns:170" in flow_ids   # 0xaa = 170
    assert "tcp:0" in flow_ids
    assert out.data["count"] == 2


def test_list_flows_attaches_dns_qname_and_tls_sni() -> None:
    records = _make_dns_pair(1, 2, "0xaa", "host.local", "1", "0") + [
        make_record(3, {
            "frame.protocols": "eth:ip:tcp",
            "tcp.flags": "0x0002", "tcp.stream": "0",
        }),
        make_record(4, {
            "frame.protocols": "eth:ip:tcp:tls",
            "tcp.stream": "0",
            "tls.handshake.type": "1",
            "tls.handshake.extensions_server_name": "host.local",
        }),
    ]
    handle = _make_handle(records)
    out = ListFlowsTool().run(_ctx(handle))
    by_id = {f["flow_id"]: f for f in out.data["flows"]}
    assert by_id["dns:170"]["dns_qname"] == "host.local"
    assert by_id["tcp:0"]["tls_sni"] == "host.local"


def test_list_flows_empty_capture() -> None:
    handle = _make_handle([])
    out = ListFlowsTool().run(_ctx(handle))
    assert out.data["count"] == 0
    assert "hint" in out.data


# ---- get_flow_timeline ----------------------------------------------------

def test_get_flow_timeline_filters_by_flow_id() -> None:
    records = _make_dns_pair(1, 2, "0xaa", "a.local", "1", "0") + _make_dns_pair(
        3, 4, "0xbb", "b.local", "1", "3"
    )
    handle = _make_handle(records)
    out = GetFlowTimelineTool().run(_ctx(handle), flow_id="dns:170")
    events = [e["event"] for e in out.data["events"]]
    assert events == ["DNS_QUERY", "DNS_RESPONSE_OK"]


def test_get_flow_timeline_requires_flow_id() -> None:
    handle = _make_handle([])
    out = GetFlowTimelineTool().run(_ctx(handle))
    assert out.data["count"] == 0
    assert "flow_id is required" in out.data["hint"]


def test_get_flow_timeline_caps_at_limit() -> None:
    records = _make_dns_pair(1, 2, "0xaa", "x.local", "1", "0") * 1
    handle = _make_handle(records)
    out = GetFlowTimelineTool().run(_ctx(handle), flow_id="dns:170", limit=1)
    assert out.data["count"] == 1


# ---- get_dns_queries ------------------------------------------------------

def test_get_dns_queries_joins_query_and_response() -> None:
    records = _make_dns_pair(1, 2, "0xaa", "x.local", "1", "3")
    handle = _make_handle(records)
    out = GetDNSQueriesTool().run(_ctx(handle))
    q = out.data["queries"][0]
    assert q["query_seq"] == 1
    assert q["response_seq"] == 2
    assert q["rcode_name"] == "NXDOMAIN"
    assert q["unanswered"] is False


def test_get_dns_queries_marks_unanswered() -> None:
    """A query frame without a matching response → unanswered=True."""
    records = [make_record(1, {
        "frame.protocols": "eth:ip:udp:dns",
        "dns.id": "0xaa", "dns.flags.response": "False",
        "dns.qry.name": "x.local", "dns.qry.type": "1",
    })]
    handle = _make_handle(records)
    out = GetDNSQueriesTool().run(_ctx(handle))
    q = out.data["queries"][0]
    assert q["unanswered"] is True
    assert q["response_seq"] is None


def test_get_dns_queries_by_name_rolls_up_dual_stack() -> None:
    """Linux glibc fires A + AAAA in parallel; AAAA NX + A OK = any_ok=True."""
    records = (
        _make_dns_pair(1, 3, "0xaa", "host.local", "1", "0")    # A → OK
        + _make_dns_pair(2, 4, "0xbb", "host.local", "28", "3") # AAAA → NX
    )
    handle = _make_handle(records)
    out = GetDNSQueriesTool().run(_ctx(handle))
    by_name = {e["qname"]: e for e in out.data["by_name"]}
    assert by_name["host.local"]["any_ok"] is True
    assert by_name["host.local"]["ok_response_count"] == 1
    assert by_name["host.local"]["nxdomain_count"] == 1


def test_get_dns_queries_filters_by_qname_substring() -> None:
    records = (
        _make_dns_pair(1, 2, "0xaa", "alpha.local", "1", "0")
        + _make_dns_pair(3, 4, "0xbb", "beta.local", "1", "0")
    )
    handle = _make_handle(records)
    out = GetDNSQueriesTool().run(_ctx(handle), qname_contains="alpha")
    assert {q["qname"] for q in out.data["queries"]} == {"alpha.local"}


# ---- get_tls_handshakes ---------------------------------------------------

def test_get_tls_handshakes_completed_likely_tls13() -> None:
    """ClientHello + ServerHello + no RST/Alert → completed_likely_tls13.

    This is the wire signature TraceWeaver routinely sees on healthy
    TLS 1.3 connections, since the Finished record is encrypted."""
    records = _make_tcp_handshake("0", base_seq=1) + [
        make_record(3, {
            "frame.protocols": "eth:ip:tcp:tls", "tcp.stream": "0",
            "tls.handshake.type": "1",
            "tls.handshake.extensions_server_name": "host.local",
        }),
        make_record(4, {
            "frame.protocols": "eth:ip:tcp:tls", "tcp.stream": "0",
            "tls.handshake.type": "2",
        }),
    ]
    handle = _make_handle(records)
    out = GetTLSHandshakesTool().run(_ctx(handle))
    hs = out.data["handshakes"][0]
    assert hs["status"] == "completed_likely_tls13"
    assert hs["sni"] == "host.local"


def test_get_tls_handshakes_rst_mid_handshake() -> None:
    """ClientHello + ServerHello + TCP_RST → rst_mid_handshake.

    This is the wire signature for a TLS 1.3 cert/SNI rejection."""
    records = _make_tcp_handshake("0", base_seq=1) + [
        make_record(3, {
            "frame.protocols": "eth:ip:tcp:tls", "tcp.stream": "0",
            "tls.handshake.type": "1",
            "tls.handshake.extensions_server_name": "broken.local",
        }),
        make_record(4, {
            "frame.protocols": "eth:ip:tcp:tls", "tcp.stream": "0",
            "tls.handshake.type": "2",
        }),
        make_record(5, {
            "frame.protocols": "eth:ip:tcp",
            "tcp.flags": "0x0014", "tcp.stream": "0",
        }),
    ]
    handle = _make_handle(records)
    out = GetTLSHandshakesTool().run(_ctx(handle))
    hs = out.data["handshakes"][0]
    assert hs["status"] == "rst_mid_handshake"
    assert hs["rst_seq"] == 5


def test_get_tls_handshakes_alert_takes_priority_over_rst() -> None:
    """A plaintext Alert (TLS 1.2) is more specific than RST."""
    records = _make_tcp_handshake("0", base_seq=1) + [
        make_record(3, {
            "frame.protocols": "eth:ip:tcp:tls", "tcp.stream": "0",
            "tls.handshake.type": "1",
        }),
        make_record(4, {
            "frame.protocols": "eth:ip:tcp:tls", "tcp.stream": "0",
            "tls.alert_message.level": "fatal",
            "tls.alert_message.desc": "Certificate Expired",
        }),
        make_record(5, {
            "frame.protocols": "eth:ip:tcp",
            "tcp.flags": "0x0014", "tcp.stream": "0",
        }),
    ]
    handle = _make_handle(records)
    out = GetTLSHandshakesTool().run(_ctx(handle))
    hs = out.data["handshakes"][0]
    assert hs["status"] == "alert"
    assert hs["alert_desc"] == "Certificate Expired"


def test_get_tls_handshakes_empty_capture() -> None:
    handle = _make_handle([])
    out = GetTLSHandshakesTool().run(_ctx(handle))
    assert out.data["count"] == 0
    assert "hint" in out.data


# ---- get_records_around ---------------------------------------------------

def test_get_records_around_returns_window() -> None:
    records = [
        make_record(s, {
            "frame.protocols": "eth:ip:tcp",
            "tcp.flags": "0x0010", "tcp.stream": "0",
        })
        for s in range(1, 11)
    ]
    handle = _make_handle(records)
    out = GetRecordsAroundTool().run(_ctx(handle), seq=5, before=2, after=2)
    seqs = [r["seq"] for r in out.data["records"]]
    assert seqs == [3, 4, 5, 6, 7]
    anchor_record = [r for r in out.data["records"] if r["is_anchor"]]
    assert len(anchor_record) == 1
    assert anchor_record[0]["seq"] == 5


def test_get_records_around_clips_at_capture_boundaries() -> None:
    records = [
        make_record(s, {
            "frame.protocols": "eth:ip:tcp",
            "tcp.flags": "0x0010", "tcp.stream": "0",
        })
        for s in range(1, 4)
    ]
    handle = _make_handle(records)
    out = GetRecordsAroundTool().run(_ctx(handle), seq=1, before=5, after=5)
    seqs = [r["seq"] for r in out.data["records"]]
    assert seqs == [1, 2, 3]


def test_get_records_around_falls_back_to_nearest_seq() -> None:
    records = [
        make_record(s, {"frame.protocols": "eth:ip"})
        for s in (10, 20, 30)
    ]
    handle = _make_handle(records)
    out = GetRecordsAroundTool().run(_ctx(handle), seq=18, before=0, after=0)
    assert [r["seq"] for r in out.data["records"]] == [20]


def test_get_records_around_requires_seq() -> None:
    handle = _make_handle([])
    out = GetRecordsAroundTool().run(_ctx(handle))
    assert out.data["count"] == 0
    assert "seq" in out.data["hint"]


# ---- declared-tool inventory ---------------------------------------------

def test_profile_declares_all_six_tools(profile) -> None:
    """The profile.yaml `tools:` block must include all six implementations."""
    declared = [t["class"] for t in profile.tools]
    assert set(declared) == {
        "SummarizeCaptureTool",
        "ListFlowsTool",
        "GetFlowTimelineTool",
        "GetDNSQueriesTool",
        "GetTLSHandshakesTool",
        "GetRecordsAroundTool",
    }
