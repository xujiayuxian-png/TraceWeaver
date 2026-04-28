"""
`summarize_capture`: capture-wide factual summary for web_l4l7_failures.

Mirrors the role `summarize_capture` plays in the 5GC profile: a single
zero-argument call that the LLM should fire FIRST, returning enough
shape information to decide which deeper tool to call next.

Output:
    event_inventory   : every event seen, with first/last seq + count
    flow_overview     : per-flow summary (TCP streams + DNS transactions)
    capture_signals   : neutral counts (no verdicts) — DNS rcode mix,
                        TCP RST count, TLS handshake completion ratio,
                        WS abnormal-disconnect count, etc.

Like 5GC's version, this tool produces NO verdicts, NO root-cause
strings, NO confidence. Those belong to the LLM after it has seen
the evidence.
"""

from __future__ import annotations

from collections import Counter, deque
from typing import Any

from traceweaver.core.protocols import Tool, ToolContext, ToolResult, ToolSpec


_MAX_FLOW_EVENTS_HEAD = 15
_MAX_FLOW_EVENTS_TAIL = 15


class SummarizeCaptureTool(Tool):
    spec = ToolSpec(
        name="summarize_capture",
        description=(
            "Return capture-wide factual inventory for the web_l4l7_failures "
            "profile: event_inventory (every DNS/TCP/TLS/WebSocket event "
            "with first/last seq), flow_overview (per-flow event list "
            "split into events_head and events_tail), and neutral "
            "capture_signals (DNS rcode mix, TCP RST count, TLS handshake "
            "completion ratio, WS abnormal-disconnect count, ...). Always "
            "inspect events_tail before concluding success: a TCP RST or "
            "WS_CONNECTION_DROPPED at the end of an otherwise healthy flow "
            "lives there. This tool produces NO verdicts."
        ),
        parameters_schema={"type": "object", "properties": {}, "required": []},
    )

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        if ctx.source_handle is None:
            return ToolResult(
                data={
                    "event_inventory": [],
                    "flow_overview": [],
                    "capture_signals": {},
                    "hint": "no source_handle",
                }
            )

        record_count = 0
        event_counts: Counter[str] = Counter()
        event_first_seq: dict[str, int] = {}
        event_last_seq: dict[str, int] = {}
        layer_counts: Counter[str] = Counter()

        # per-flow accumulator. flow_id -> aggregated state.
        flows: dict[str, dict[str, Any]] = {}

        # signal counters
        dns_rcode_mix: Counter[str] = Counter()
        # Track per-stream TLS state. We classify the same way
        # `get_tls_handshakes` does (and FOR THE SAME REASON: TLS 1.3
        # encrypts Finished, so "ServerHello seen + no failure signal"
        # is the happy-path wire pattern, NOT a failure).
        tls_started_streams: set[int] = set()
        tls_server_hello_streams: set[int] = set()
        tls_finished_streams: set[int] = set()    # plaintext type=20, TLS ≤1.2 only
        tls_alert_streams: set[int] = set()
        tls_rst_streams: set[int] = set()
        tcp_rst_count = 0
        tcp_retransmit_count = 0
        ws_close_frame_count = 0
        ws_streams_seen: set[int] = set()

        for rec in ctx.source_handle.iter_records():
            record_count += 1
            f = rec.fields
            layer = str(f.get("protocol_layer") or "other")
            layer_counts[layer] += 1
            ev = f.get("event")
            ev_str = str(ev) if ev else None
            if ev_str is not None:
                event_counts[ev_str] += 1
                event_first_seq.setdefault(ev_str, rec.seq)
                event_last_seq[ev_str] = rec.seq

            flow_id = f.get("flow_id")
            if flow_id and ev_str is not None:
                slot = flows.setdefault(
                    str(flow_id),
                    {
                        "flow_id": str(flow_id),
                        "first_seq": rec.seq,
                        "last_seq": rec.seq,
                        "event_count": 0,
                        "event_counts": Counter(),
                        "events_head": [],
                        "events_tail": deque(maxlen=_MAX_FLOW_EVENTS_TAIL),
                        "src_ip": f.get("src_ip"),
                        "dst_ip": f.get("dst_ip"),
                        "src_port": f.get("src_port"),
                        "dst_port": f.get("dst_port"),
                        "tls_sni": None,
                        "dns_qname": None,
                    },
                )
                slot["last_seq"] = rec.seq
                slot["event_count"] += 1
                slot["event_counts"][ev_str] += 1
                if len(slot["events_head"]) < _MAX_FLOW_EVENTS_HEAD:
                    slot["events_head"].append(ev_str)
                else:
                    slot["events_tail"].append(ev_str)
                if slot.get("tls_sni") is None and f.get("tls_sni"):
                    slot["tls_sni"] = f.get("tls_sni")
                if slot.get("dns_qname") is None and f.get("dns_qname"):
                    slot["dns_qname"] = f.get("dns_qname")

            # signals
            rcode_name = f.get("dns_rcode_name")
            if rcode_name:
                dns_rcode_mix[str(rcode_name)] += 1
            tcp_stream = f.get("tcp_stream")
            if isinstance(tcp_stream, int):
                if ev_str == "TLS_CLIENT_HELLO":
                    tls_started_streams.add(tcp_stream)
                if ev_str == "TLS_SERVER_HELLO":
                    tls_server_hello_streams.add(tcp_stream)
                if ev_str == "TLS_FINISHED":
                    tls_finished_streams.add(tcp_stream)
                if f.get("tls_alert_desc"):
                    tls_alert_streams.add(tcp_stream)
                if ev_str == "TCP_RST":
                    tcp_rst_count += 1
                    # Only count as a TLS-layer RST if a Client Hello
                    # was already seen on this stream — otherwise it's
                    # just a plain TCP RST (port closed etc.) and
                    # belongs to TCP signals, not TLS signals.
                    if tcp_stream in tls_started_streams:
                        tls_rst_streams.add(tcp_stream)
                if f.get("is_retransmit") is True:
                    tcp_retransmit_count += 1
                if f.get("ws_opcode") is not None:
                    ws_streams_seen.add(tcp_stream)
            if ev_str == "WS_CLOSE":
                ws_close_frame_count += 1

        event_inventory = [
            {
                "event": ev,
                "count": event_counts[ev],
                "first_seq": event_first_seq[ev],
                "last_seq": event_last_seq[ev],
            }
            for ev in sorted(event_counts, key=lambda e: event_first_seq[e])
        ]

        flow_overview = []
        for slot in sorted(flows.values(), key=lambda s: s["first_seq"]):
            head = list(slot["events_head"])
            tail = list(slot["events_tail"])
            total = slot["event_count"]
            truncated = max(0, total - len(head) - len(tail))
            flow_overview.append(
                {
                    "flow_id": slot["flow_id"],
                    "first_seq": slot["first_seq"],
                    "last_seq": slot["last_seq"],
                    "event_count": total,
                    "event_counts": dict(slot["event_counts"]),
                    "events_head": head,
                    "events_tail": tail,
                    "events_truncated_count": truncated,
                    "src_ip": slot["src_ip"],
                    "dst_ip": slot["dst_ip"],
                    "src_port": slot["src_port"],
                    "dst_port": slot["dst_port"],
                    "tls_sni": slot["tls_sni"],
                    "dns_qname": slot["dns_qname"],
                }
            )

        # WS abnormal disconnect: a TCP stream that carried any WS frame
        # AND ended with TCP_RST WITHOUT a preceding WS_CLOSE event in
        # that same flow.
        ws_abnormal_disconnect_count = 0
        for slot in flow_overview:
            ec = slot["event_counts"]
            if "TCP_RST" in ec and ec.get("WS_CLOSE", 0) == 0:
                # only count flows that actually were a WebSocket
                # (had a WS_HANDSHAKE_RESPONSE_OK or any ws frame event)
                ws_events_in_flow = sum(
                    n for k, n in ec.items()
                    if k.startswith("WS_") and k != "WS_CLOSE"
                )
                if ws_events_in_flow > 0:
                    ws_abnormal_disconnect_count += 1

        capture_signals = {
            "record_count": record_count,
            "event_count": sum(event_counts.values()),
            "flow_count": len(flow_overview),
            "protocol_layer_counts": dict(layer_counts),
            # DNS
            "dns_query_count": event_counts["DNS_QUERY"],
            "dns_response_count": sum(
                count for ev, count in event_counts.items()
                if ev.startswith("DNS_RESPONSE_")
            ),
            "dns_rcode_mix": dict(dns_rcode_mix),
            "dns_nxdomain_count": event_counts["DNS_RESPONSE_NXDOMAIN"],
            "dns_servfail_count": event_counts["DNS_RESPONSE_SERVFAIL"],
            "dns_refused_count": event_counts["DNS_RESPONSE_REFUSED"],
            # TCP
            "tcp_syn_count": event_counts["TCP_SYN"],
            "tcp_syn_ack_count": event_counts["TCP_SYN_ACK"],
            "tcp_fin_count": event_counts["TCP_FIN"],
            "tcp_rst_count": tcp_rst_count,
            "tcp_unanswered_syn_count": max(
                0, event_counts["TCP_SYN"] - event_counts["TCP_SYN_ACK"]
            ),
            "tcp_retransmit_count": tcp_retransmit_count,
            # TLS — `failed` is "started + had alert OR RST"; `completed`
            # is "started + ServerHello seen + no failure signal", which
            # is the TLS 1.3 happy path (Finished is encrypted).
            "tls_handshake_started_count": len(tls_started_streams),
            "tls_handshake_completed_count": len(
                (tls_finished_streams | tls_server_hello_streams)
                - tls_alert_streams
                - tls_rst_streams
            ),
            "tls_handshake_failed_count": len(
                (tls_alert_streams | tls_rst_streams) & tls_started_streams
            ),
            "tls_alert_count": event_counts["TLS_ALERT"],
            # WebSocket
            "ws_handshake_request_count": event_counts["WS_HANDSHAKE_REQUEST"],
            "ws_handshake_response_ok_count": event_counts["WS_HANDSHAKE_RESPONSE_OK"],
            "ws_close_frame_count": ws_close_frame_count,
            "ws_stream_count": len(ws_streams_seen),
            "ws_abnormal_disconnect_count": ws_abnormal_disconnect_count,
        }

        return ToolResult(
            data={
                "event_inventory": event_inventory,
                "flow_overview": flow_overview,
                "capture_signals": capture_signals,
            }
        )


__all__ = ["SummarizeCaptureTool"]
