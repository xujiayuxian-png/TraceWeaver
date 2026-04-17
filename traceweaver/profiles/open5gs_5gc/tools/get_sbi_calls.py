"""
`get_sbi_calls`: list HTTP/2 SBI requests and responses from the capture.

In Open5GS, 5GC NFs talk over HTTP/2 on TCP 7777 by default. This tool
collapses per-frame http2 headers into one entry per SBI call using
`http2.streamid` within a TCP stream, and returns `{seq, ts, method,
path, status, authority, host}`.

Why an own tool (and not `query_records`)?  The LLM would otherwise
need two or three round-trips to correlate method/path frames with
status frames; doing it here keeps the prompt terse.
"""

from __future__ import annotations

from typing import Any

from traceweaver.core.tools.base import Tool, ToolContext, ToolResult, ToolSpec


_DEFAULT_LIMIT = 50
_MAX_LIMIT = 300


class GetSBICallsTool(Tool):
    spec = ToolSpec(
        name="get_sbi_calls",
        description=(
            "List HTTP/2 SBI calls observed in the capture, one entry per "
            "(tcp.stream, http2.streamid). Each entry carries "
            "`{first_seq, last_seq, timestamp, method, path, status, "
            "authority}` where `status` is the HTTP response code when a "
            "response was seen. Useful for investigating Namf_*, Nudm_*, "
            "Nsmf_*, Nausf_* failures. Filter with `path_contains` (case-"
            "insensitive substring) to narrow down to one service."
        ),
        parameters_schema={
            "type": "object",
            "properties": {
                "path_contains": {"type": "string"},
                "method": {"type": "string"},
                "status": {"type": "integer"},
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": _MAX_LIMIT,
                },
            },
            "required": [],
        },
    )

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        if ctx.source_handle is None:
            return ToolResult(
                data={"calls": [], "count": 0, "hint": "no source_handle"},
            )

        path_needle = (kwargs.get("path_contains") or "").lower() or None
        method_wanted = kwargs.get("method") or None
        status_wanted = kwargs.get("status")
        try:
            limit = int(kwargs.get("limit") or _DEFAULT_LIMIT)
        except (TypeError, ValueError):
            limit = _DEFAULT_LIMIT
        limit = max(1, min(limit, _MAX_LIMIT))

        calls: dict[tuple[str, str], dict[str, Any]] = {}
        for rec in ctx.source_handle.iter_records():
            f = rec.fields
            stream_id = f.get("http2.streamid")
            if not stream_id:
                continue
            tcp_stream = f.get("tcp.stream") or ""
            key = (str(tcp_stream), str(stream_id))

            method = f.get("http2.headers.method")
            path = f.get("http2.headers.path")
            status = f.get("http2.headers.status")
            authority = f.get("http2.headers.authority") or f.get("http2.headers.host")

            slot = calls.setdefault(
                key,
                {
                    "tcp_stream": tcp_stream,
                    "stream_id": stream_id,
                    "first_seq": rec.seq,
                    "last_seq": rec.seq,
                    "timestamp": rec.timestamp,
                    "method": None,
                    "path": None,
                    "status": None,
                    "authority": None,
                    "src_ip": f.get("src_ip"),
                    "dst_ip": f.get("dst_ip"),
                },
            )
            slot["last_seq"] = rec.seq
            if method and not slot["method"]:
                slot["method"] = method
            if path and not slot["path"]:
                slot["path"] = path
            if authority and not slot["authority"]:
                slot["authority"] = authority
            if status and not slot["status"]:
                try:
                    slot["status"] = int(str(status).split(",", 1)[0])
                except ValueError:
                    slot["status"] = status

        merged = sorted(calls.values(), key=lambda c: (c["first_seq"],))

        out: list[dict[str, Any]] = []
        for c in merged:
            if path_needle and path_needle not in (c.get("path") or "").lower():
                continue
            if method_wanted and (c.get("method") or "") != method_wanted:
                continue
            if status_wanted is not None and c.get("status") != status_wanted:
                continue
            out.append(c)
            if len(out) >= limit:
                break

        data: dict[str, Any] = {"calls": out, "count": len(out)}
        if not out:
            data["hint"] = (
                "no SBI calls matched. If the capture covers radio-only "
                "traffic, HTTP/2 will be absent — try list_ue_sessions "
                "and get_ue_timeline instead."
            )
        return ToolResult(data=data)


__all__ = ["GetSBICallsTool"]
