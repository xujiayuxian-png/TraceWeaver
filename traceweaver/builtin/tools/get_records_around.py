"""get_records_around: retrieve a window of records centered on a seq."""
from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field
from traceweaver.core.protocols import Tool, ToolContext, ToolResult, ToolSpec

_MAX_WINDOW = 20

def _clamp(value: Any, lo: int, hi: int) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        return lo
    return max(lo, min(v, hi))

class GetRecordsAroundArgs(BaseModel):
    seq: int = Field(description="Anchor seq (frame.number or log line)")
    before: int = Field(default=2, description="Records before anchor (0-20)")
    after: int = Field(default=2, description="Records after anchor (0-20)")

class GetRecordsAroundTool(Tool):
    spec = ToolSpec.from_pydantic(
        GetRecordsAroundArgs,
        name="get_records_around",
        description="Return records immediately before and after a given seq anchor.",
    )

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        if ctx.source_handle is None:
            return ToolResult(data={"records": [], "count": 0, "hint": "no source loaded"})

        try:
            args = GetRecordsAroundArgs.model_validate(kwargs)
        except Exception as e:
            return ToolResult(data={"records": [], "count": 0, "hint": f"invalid arguments: {e}"})

        seq = args.seq
        before = _clamp(args.before, 0, _MAX_WINDOW)
        after = _clamp(args.after, 0, _MAX_WINDOW)

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
