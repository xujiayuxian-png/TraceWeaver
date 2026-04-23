"""get_records_around: retrieve a window of records centered on a seq."""
from __future__ import annotations
from typing import Any
from traceweaver.core.protocols import Tool, ToolContext, ToolResult, ToolSpec

_MAX_WINDOW = 20

def _clamp(value: Any, lo: int, hi: int) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        return lo
    return max(lo, min(v, hi))

class GetRecordsAroundTool(Tool):
    spec = ToolSpec(
        name="get_records_around",
        description="Return records immediately before and after a given seq anchor.",
        parameters_schema={
            "type": "object",
            "properties": {
                "seq": {"type": "integer", "description": "Anchor seq (frame.number or log line)"},
                "before": {"type": "integer", "description": "Records before anchor (0-20)", "minimum": 0, "maximum": _MAX_WINDOW},
                "after": {"type": "integer", "description": "Records after anchor (0-20)", "minimum": 0, "maximum": _MAX_WINDOW},
            },
            "required": ["seq"],
        },
    )

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        if ctx.source_handle is None:
            return ToolResult(data={"records": [], "count": 0, "hint": "no source loaded"})

        try:
            seq = int(kwargs["seq"])
        except (KeyError, TypeError, ValueError):
            return ToolResult(data={"records": [], "count": 0, "hint": "seq must be an integer"})

        before = _clamp(kwargs.get("before", 2), 0, _MAX_WINDOW)
        after = _clamp(kwargs.get("after", 2), 0, _MAX_WINDOW)

        window = ctx.source_handle.get_records_around(seq, before=before, after=after)
        rows: list[dict[str, Any]] = []
        refs: list[str] = []
        for rec in window:
            rows.append({"source": rec.source, "seq": rec.seq, "timestamp": rec.timestamp, "key": rec.key, "fields": rec.fields})
            refs.append(f"{rec.source}:seq={rec.seq}")

        data: dict[str, Any] = {"records": rows, "count": len(rows), "anchor_seq": seq}
        if not rows:
            data["hint"] = f"no records near seq={seq}"
        return ToolResult(data=data, refs=refs)

__all__ = ["GetRecordsAroundTool"]
