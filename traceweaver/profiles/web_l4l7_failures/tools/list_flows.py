"""
`list_flows`: enumerate every flow observed in the capture.

Mirror of 5GC's `list_ue_sessions`: an LLM should call this when it
doesn't yet know which flow is interesting. Each flow corresponds to
either a TCP stream (`tcp:<n>`) or a DNS transaction (`dns:<id>`).

Output: `flows: [{flow_id, transport, first_seq, last_seq, event_count,
first_event, last_event, src_ip, dst_ip, dst_port, tls_sni, dns_qname,
event_counts}, ...]`.

The flows are ordered by `first_seq`; the LLM can treat earlier flows as
"happened first" without having to look at the (less stable) timestamps.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from traceweaver.core.protocols import Tool, ToolContext, ToolResult, ToolSpec


class ListFlowsTool(Tool):
    spec = ToolSpec(
        name="list_flows",
        description=(
            "List every flow observed in the loaded capture. A flow is "
            "either a TCP stream (`tcp:<n>`) or a DNS transaction "
            "(`dns:<id>`). For each flow returns transport, first/last "
            "seq, frame count, first/last event, src/dst IP, dst port, "
            "TLS SNI (if any), DNS qname (if any), and an event-name "
            "histogram. Call this FIRST when you don't yet know which "
            "flow is interesting. No arguments; returns "
            "`{flows: [...], count}`."
        ),
        parameters_schema={"type": "object", "properties": {}, "required": []},
    )

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        if ctx.source_handle is None:
            return ToolResult(
                data={"flows": [], "count": 0, "hint": "no source_handle"},
            )

        groups: dict[str, dict[str, Any]] = {}

        for rec in ctx.source_handle.iter_records():
            f = rec.fields
            flow_id = f.get("flow_id")
            if not flow_id:
                continue
            key = str(flow_id)
            slot = groups.setdefault(
                key,
                {
                    "flow_id": key,
                    "transport": f.get("transport"),
                    "first_seq": rec.seq,
                    "last_seq": rec.seq,
                    "first_event": None,
                    "last_event": None,
                    "frames": 0,
                    "event_counts": Counter(),
                    "src_ip": f.get("src_ip"),
                    "dst_ip": f.get("dst_ip"),
                    "src_port": f.get("src_port"),
                    "dst_port": f.get("dst_port"),
                    "tls_sni": None,
                    "dns_qname": None,
                },
            )
            slot["frames"] += 1
            slot["last_seq"] = rec.seq

            ev = f.get("event")
            ev_str = str(ev) if ev else None
            if ev_str:
                if slot["first_event"] is None:
                    slot["first_event"] = ev_str
                slot["last_event"] = ev_str
                slot["event_counts"][ev_str] += 1

            # Attach session-identifying details the first time we see them.
            if slot["tls_sni"] is None and f.get("tls_sni"):
                slot["tls_sni"] = f.get("tls_sni")
            if slot["dns_qname"] is None and f.get("dns_qname"):
                slot["dns_qname"] = f.get("dns_qname")

        flows = []
        for slot in sorted(groups.values(), key=lambda s: s["first_seq"]):
            flows.append(
                {
                    "flow_id": slot["flow_id"],
                    "transport": slot["transport"],
                    "first_seq": slot["first_seq"],
                    "last_seq": slot["last_seq"],
                    "frames": slot["frames"],
                    "first_event": slot["first_event"],
                    "last_event": slot["last_event"],
                    "event_counts": dict(slot["event_counts"]),
                    "src_ip": slot["src_ip"],
                    "dst_ip": slot["dst_ip"],
                    "src_port": slot["src_port"],
                    "dst_port": slot["dst_port"],
                    "tls_sni": slot["tls_sni"],
                    "dns_qname": slot["dns_qname"],
                }
            )

        data: dict[str, Any] = {"flows": flows, "count": len(flows)}
        if not flows:
            data["hint"] = (
                "no flows found. The capture may contain only ARP / ICMP "
                "noise — try `summarize_capture` to see what's there."
            )
        return ToolResult(data=data)


__all__ = ["ListFlowsTool"]
