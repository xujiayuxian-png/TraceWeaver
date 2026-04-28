"""
`get_flow_timeline`: ordered events for a specific flow.

The LLM calls this once it has picked a flow_id from `list_flows` (or
inferred it from `summarize_capture` output). Returns one dict per
frame that has an `event`, with the fields a diagnosis actually needs.
"""

from __future__ import annotations

from typing import Any

from traceweaver.core.protocols import Tool, ToolContext, ToolResult, ToolSpec


_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200


class GetFlowTimelineTool(Tool):
    spec = ToolSpec(
        name="get_flow_timeline",
        description=(
            "Return the ordered timeline of events for a specific flow "
            "(call `list_flows` first to discover valid flow_id values "
            "like 'tcp:0' or 'dns:12345'). Only frames carrying an "
            "`event` are returned; each has `{seq, timestamp, event, "
            "protocol_layer, src_ip, dst_ip, dns_rcode_name, "
            "tls_handshake_type, tls_sni, ws_opcode_name, "
            "tcp_flag_names, is_retransmit}`. Use `limit` to cap output "
            "(default 50, max 200)."
        ),
        parameters_schema={
            "type": "object",
            "properties": {
                "flow_id": {
                    "type": "string",
                    "description": (
                        "Flow identifier of the form 'tcp:<n>' or "
                        "'dns:<n>' as returned by list_flows."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": _MAX_LIMIT,
                },
            },
            "required": ["flow_id"],
        },
    )

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        if ctx.source_handle is None:
            return ToolResult(
                data={"events": [], "count": 0, "hint": "no source_handle"},
            )

        flow_id = kwargs.get("flow_id")
        if not flow_id or not isinstance(flow_id, str):
            return ToolResult(
                data={
                    "events": [],
                    "count": 0,
                    "hint": (
                        "flow_id is required; call list_flows to see the "
                        "valid identifiers (e.g. 'tcp:0', 'dns:12345')."
                    ),
                },
            )

        try:
            limit = int(kwargs.get("limit") or _DEFAULT_LIMIT)
        except (TypeError, ValueError):
            limit = _DEFAULT_LIMIT
        limit = max(1, min(limit, _MAX_LIMIT))

        events: list[dict[str, Any]] = []
        for rec in ctx.source_handle.iter_records():
            if rec.fields.get("event") is None:
                continue
            if rec.fields.get("flow_id") != flow_id:
                continue
            events.append(
                {
                    "seq": rec.seq,
                    "timestamp": rec.timestamp,
                    "event": rec.fields.get("event"),
                    "protocol_layer": rec.fields.get("protocol_layer"),
                    "src_ip": rec.fields.get("src_ip"),
                    "dst_ip": rec.fields.get("dst_ip"),
                    "src_port": rec.fields.get("src_port"),
                    "dst_port": rec.fields.get("dst_port"),
                    "dns_rcode_name": rec.fields.get("dns_rcode_name"),
                    "dns_qname": rec.fields.get("dns_qname"),
                    "dns_qtype_name": rec.fields.get("dns_qtype_name"),
                    "tls_handshake_type": rec.fields.get("tls_handshake_type"),
                    "tls_sni": rec.fields.get("tls_sni"),
                    "tls_alert_desc": rec.fields.get("tls_alert_desc"),
                    "ws_opcode_name": rec.fields.get("ws_opcode_name"),
                    "tcp_flag_names": rec.fields.get("tcp_flag_names"),
                    "is_retransmit": rec.fields.get("is_retransmit"),
                }
            )
            if len(events) >= limit:
                break

        data: dict[str, Any] = {
            "events": events,
            "count": len(events),
            "filter": {"flow_id": flow_id},
        }
        if not events:
            data["hint"] = (
                f"no events match flow_id={flow_id!r}. Confirm with "
                f"list_flows (the flow may have produced only noise frames)."
            )
        return ToolResult(data=data)


__all__ = ["GetFlowTimelineTool"]
