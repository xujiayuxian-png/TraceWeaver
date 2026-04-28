"""
`get_records_around`: return a window of frames centred on a given seq.

Generic context tool — when the LLM has identified an "anchor" frame
(typically a `TCP_RST` or `TLS_ALERT`) and wants to see what happened
right before / after it. Mirrors the `get_records_around` tool the
5GC profile exposes.
"""

from __future__ import annotations

from typing import Any

from traceweaver.core.protocols import Tool, ToolContext, ToolResult, ToolSpec


_DEFAULT_BEFORE = 2
_DEFAULT_AFTER = 2
_MAX_WINDOW = 20


class GetRecordsAroundTool(Tool):
    spec = ToolSpec(
        name="get_records_around",
        description=(
            "Return frames immediately before and after a given seq "
            "anchor. Each frame includes `{seq, timestamp, event, "
            "protocol_layer, src_ip, dst_ip, src_port, dst_port, "
            "tcp_flag_names, dns_qname, tls_sni, ws_opcode_name}`. "
            "`before` and `after` default to 2; max 20 each. Use this "
            "after spotting an anchor event (e.g. a TCP_RST or "
            "TLS_ALERT) to see what happened right around it."
        ),
        parameters_schema={
            "type": "object",
            "properties": {
                "seq": {
                    "type": "integer",
                    "description": "Anchor seq (frame.number).",
                },
                "before": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": _MAX_WINDOW,
                    "description": "Frames before the anchor (default 2).",
                },
                "after": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": _MAX_WINDOW,
                    "description": "Frames after the anchor (default 2).",
                },
            },
            "required": ["seq"],
        },
    )

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        if ctx.source_handle is None:
            return ToolResult(
                data={"records": [], "count": 0, "hint": "no source_handle"},
            )

        try:
            anchor = int(kwargs.get("seq"))
        except (TypeError, ValueError):
            return ToolResult(
                data={
                    "records": [],
                    "count": 0,
                    "hint": "`seq` is required (integer frame number).",
                },
            )

        # Note: `or _DEFAULT_*` is wrong here because `before=0` is a
        # legitimate caller intent ("just the anchor frame"); only treat
        # an actually-missing key as default.
        before_raw = kwargs.get("before")
        after_raw = kwargs.get("after")
        try:
            before = _DEFAULT_BEFORE if before_raw is None else int(before_raw)
        except (TypeError, ValueError):
            before = _DEFAULT_BEFORE
        try:
            after = _DEFAULT_AFTER if after_raw is None else int(after_raw)
        except (TypeError, ValueError):
            after = _DEFAULT_AFTER
        before = max(0, min(before, _MAX_WINDOW))
        after = max(0, min(after, _MAX_WINDOW))

        # We don't assume the source handle supports random access, so
        # we materialize the window with a single linear scan.
        records: list[Any] = list(ctx.source_handle.iter_records())
        # Map seq -> index for fast lookup. Records are ordered so a
        # bisect would be cheaper, but with capture sizes <100k the
        # dict approach is plenty.
        seq_to_idx = {r.seq: idx for idx, r in enumerate(records)}
        idx = seq_to_idx.get(anchor)
        if idx is None:
            # Fall back: pick the closest record by seq.
            if not records:
                return ToolResult(
                    data={"records": [], "count": 0, "hint": "capture is empty"},
                )
            idx = min(range(len(records)), key=lambda i: abs(records[i].seq - anchor))

        lo = max(0, idx - before)
        hi = min(len(records), idx + after + 1)
        window = []
        for r in records[lo:hi]:
            f = r.fields
            window.append(
                {
                    "seq": r.seq,
                    "timestamp": r.timestamp,
                    "event": f.get("event"),
                    "protocol_layer": f.get("protocol_layer"),
                    "src_ip": f.get("src_ip"),
                    "dst_ip": f.get("dst_ip"),
                    "src_port": f.get("src_port"),
                    "dst_port": f.get("dst_port"),
                    "tcp_flag_names": f.get("tcp_flag_names"),
                    "dns_qname": f.get("dns_qname"),
                    "dns_rcode_name": f.get("dns_rcode_name"),
                    "tls_sni": f.get("tls_sni"),
                    "tls_handshake_type": f.get("tls_handshake_type"),
                    "tls_alert_desc": f.get("tls_alert_desc"),
                    "ws_opcode_name": f.get("ws_opcode_name"),
                    "is_anchor": r.seq == anchor,
                }
            )

        return ToolResult(
            data={
                "records": window,
                "count": len(window),
                "anchor": anchor,
                "before": before,
                "after": after,
            }
        )


__all__ = ["GetRecordsAroundTool"]
