"""
`summarize_capture`: per-UE event summary.

Returns a minimal summary per UE: events list, event count, first/last seq, and UE key.
"""
from __future__ import annotations
from typing import Any
from traceweaver.core.protocols import Tool, ToolContext, ToolResult, ToolSpec

_MAX_UE_EVENTS = 50

class SummarizeCaptureTool(Tool):
    spec = ToolSpec(
        name="summarize_capture",
        description="Return per-UE event summary: events list, count, first/last seq, UE key.",
        parameters_schema={"type": "object", "properties": {}, "required": []},
    )

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        if ctx.source_handle is None:
            return ToolResult(data={"ue_overview": [], "hint": "no source_handle"})

        ue_events: dict[str, list[str]] = {}
        ue_first_seq: dict[str, int] = {}
        ue_last_seq: dict[str, int] = {}

        for rec in ctx.source_handle.iter_records():
            f = rec.fields
            ev = f.get("event")
            ran = f.get("ran_ue_ngap_id")
            if ran is not None and ev:
                key = str(ran)
                evs = ue_events.setdefault(key, [])
                if len(evs) < _MAX_UE_EVENTS:
                    evs.append(str(ev))
                ue_first_seq.setdefault(key, rec.seq)
                ue_last_seq[key] = rec.seq

        ue_overview = [
            {
                "ran_ue_ngap_id": key,
                "first_seq": ue_first_seq[key],
                "last_seq": ue_last_seq[key],
                "event_count": len(ue_events[key]),
                "events": ue_events[key],
            }
            for key in sorted(ue_events, key=lambda k: ue_first_seq[k])
        ]

        return ToolResult(data={"ue_overview": ue_overview})


__all__ = ["SummarizeCaptureTool"]
