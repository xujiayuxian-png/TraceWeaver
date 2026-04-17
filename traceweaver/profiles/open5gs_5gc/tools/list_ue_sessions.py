"""
`list_ue_sessions`: group enriched records by (ran_ue_ngap_id, amf_ue_ngap_id).

Every 5GC investigation starts with "how many UEs are here and what did
each of them do?". This tool answers that in one call, so the LLM does
NOT need to manually scan and group via `query_records`.

Output: `sessions: [{ran_ue_ngap_id, amf_ue_ngap_id, frames, first_seq,
last_seq, first_event, last_event, event_counts: {...}}, ...]`.
"""

from __future__ import annotations

from typing import Any

from traceweaver.core.tools.base import Tool, ToolContext, ToolResult, ToolSpec


class ListUESessionsTool(Tool):
    spec = ToolSpec(
        name="list_ue_sessions",
        description=(
            "List every UE session observed in the loaded capture, keyed "
            "by (ran_ue_ngap_id, amf_ue_ngap_id). For each session returns "
            "the frame count, first/last seq, first/last event name, and a "
            "histogram of event names. Call this FIRST when you don't yet "
            "know which UE is interesting. No arguments; returns "
            "`{sessions: [...], count}`."
        ),
        parameters_schema={"type": "object", "properties": {}, "required": []},
    )

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        if ctx.source_handle is None:
            return ToolResult(
                data={"sessions": [], "count": 0, "hint": "no source_handle"},
            )

        groups: dict[tuple[str, str], dict[str, Any]] = {}
        for rec in ctx.source_handle.iter_records():
            ran = rec.fields.get("ran_ue_ngap_id")
            amf = rec.fields.get("amf_ue_ngap_id")
            if ran is None and amf is None:
                # Skip frames with no UE identity at all (OAM, heartbeats).
                continue
            key = (str(ran or ""), str(amf or ""))
            slot = groups.setdefault(
                key,
                {
                    "ran_ue_ngap_id": ran,
                    "amf_ue_ngap_id": amf,
                    "frames": 0,
                    "first_seq": rec.seq,
                    "last_seq": rec.seq,
                    "first_event": rec.fields.get("event"),
                    "last_event": rec.fields.get("event"),
                    "event_counts": {},
                },
            )
            slot["frames"] += 1
            slot["last_seq"] = rec.seq
            if slot["first_event"] is None:
                slot["first_event"] = rec.fields.get("event")
            ev = rec.fields.get("event")
            if ev:
                slot["last_event"] = ev
                counts: dict[str, int] = slot["event_counts"]
                counts[ev] = counts.get(ev, 0) + 1

        sessions = sorted(
            groups.values(),
            key=lambda s: (s["first_seq"], s.get("ran_ue_ngap_id") or ""),
        )
        data: dict[str, Any] = {
            "sessions": sessions,
            "count": len(sessions),
        }
        if not sessions:
            data["hint"] = (
                "no UE sessions found. The capture may contain only "
                "non-UE traffic (heartbeats, SBI control, PFCP association)."
            )
        return ToolResult(data=data)


__all__ = ["ListUESessionsTool"]
