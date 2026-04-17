"""
`get_ue_timeline`: all enriched events for a given UE, in order.

The LLM calls this once it has picked a UE from `list_ue_sessions` (or
inferred an id from user text). The output is compact: one dict per
frame that has an `event`, with just the fields a diagnosis needs.
"""

from __future__ import annotations

from typing import Any

from traceweaver.core.tools.base import Tool, ToolContext, ToolResult, ToolSpec


_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200


def _match(rec_fields: dict[str, Any], ran: str | None, amf: str | None) -> bool:
    if ran is not None:
        if str(rec_fields.get("ran_ue_ngap_id") or "") != ran:
            return False
    if amf is not None:
        if str(rec_fields.get("amf_ue_ngap_id") or "") != amf:
            return False
    return True


class GetUETimelineTool(Tool):
    spec = ToolSpec(
        name="get_ue_timeline",
        description=(
            "Return the ordered timeline of NAS/NGAP events for a specific "
            "UE. Provide at least one of `ran_ue_ngap_id` or "
            "`amf_ue_ngap_id` (use the string form returned by "
            "`list_ue_sessions`). Only frames that carry an `event` field "
            "are returned; each has `{seq, timestamp, event, "
            "protocol_layer, mm_cause, sm_cause, src_ip, dst_ip}`. "
            "Use `limit` to cap output (default 50, max 200)."
        ),
        parameters_schema={
            "type": "object",
            "properties": {
                "ran_ue_ngap_id": {"type": "string"},
                "amf_ue_ngap_id": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": _MAX_LIMIT},
            },
            "required": [],
        },
    )

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        if ctx.source_handle is None:
            return ToolResult(
                data={"events": [], "count": 0, "hint": "no source_handle"},
            )

        ran = kwargs.get("ran_ue_ngap_id")
        amf = kwargs.get("amf_ue_ngap_id")
        if ran in (None, ""):
            ran = None
        else:
            ran = str(ran)
        if amf in (None, ""):
            amf = None
        else:
            amf = str(amf)
        if ran is None and amf is None:
            return ToolResult(
                data={
                    "events": [],
                    "count": 0,
                    "hint": (
                        "provide at least one of ran_ue_ngap_id / "
                        "amf_ue_ngap_id; call list_ue_sessions first to see "
                        "the valid values."
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
            if not _match(rec.fields, ran, amf):
                continue
            events.append(
                {
                    "seq": rec.seq,
                    "timestamp": rec.timestamp,
                    "event": rec.fields.get("event"),
                    "protocol_layer": rec.fields.get("protocol_layer"),
                    "mm_cause": rec.fields.get("mm_cause"),
                    "sm_cause": rec.fields.get("sm_cause"),
                    "src_ip": rec.fields.get("src_ip"),
                    "dst_ip": rec.fields.get("dst_ip"),
                    "pdu_session_id": rec.fields.get("pdu_session_id"),
                }
            )
            if len(events) >= limit:
                break

        data: dict[str, Any] = {
            "events": events,
            "count": len(events),
            "filter": {"ran_ue_ngap_id": ran, "amf_ue_ngap_id": amf},
        }
        if not events:
            data["hint"] = (
                "no events match. Confirm the UE id with list_ue_sessions "
                "(values are strings, and missing ids are returned as empty)."
            )
        return ToolResult(data=data)


__all__ = ["GetUETimelineTool"]
