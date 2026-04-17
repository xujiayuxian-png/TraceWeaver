"""
`get_records_around`: retrieve a window of records centered on a seq.

The most common follow-up after `query_records` locates an interesting
event ("frame 47 was the 403"): the LLM wants the surrounding context
to reason about causality. This tool is a thin wrapper over the source
handle's `get_records_around`.
"""

from __future__ import annotations

from typing import Any

from traceweaver.core.tools.base import Tool, ToolContext, ToolResult, ToolSpec


_MAX_WINDOW = 20


class GetRecordsAroundTool(Tool):
    spec = ToolSpec(
        name="get_records_around",
        description=(
            "Return the records immediately before and after a given `seq` "
            "anchor (frame number / log line). `before` and `after` default "
            "to 2, max 20 each. Useful for inspecting what happened right "
            "before/after a suspect event. Returns `{records: [...], anchor_seq, count}`."
        ),
        parameters_schema={
            "type": "object",
            "properties": {
                "seq": {
                    "type": "integer",
                    "description": "The anchor seq (frame.number or log line number).",
                },
                "before": {
                    "type": "integer",
                    "description": "How many records before the anchor (0-20).",
                    "minimum": 0,
                    "maximum": _MAX_WINDOW,
                },
                "after": {
                    "type": "integer",
                    "description": "How many records after the anchor (0-20).",
                    "minimum": 0,
                    "maximum": _MAX_WINDOW,
                },
            },
            "required": ["seq"],
        },
    )

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        if ctx.source_handle is None:
            return ToolResult(
                data={
                    "records": [],
                    "count": 0,
                    "hint": "no source is loaded in this context; the kernel must provide source_handle.",
                },
            )

        try:
            seq = int(kwargs["seq"])
        except (KeyError, TypeError, ValueError):
            return ToolResult(
                data={
                    "records": [],
                    "count": 0,
                    "hint": "`seq` is required and must be an integer.",
                },
            )

        before = _clamp(kwargs.get("before", 2), 0, _MAX_WINDOW)
        after = _clamp(kwargs.get("after", 2), 0, _MAX_WINDOW)

        window = ctx.source_handle.get_records_around(
            seq, before=before, after=after
        )
        rows: list[dict[str, Any]] = []
        refs: list[str] = []
        for rec in window:
            rows.append(
                {
                    "source": rec.source,
                    "seq": rec.seq,
                    "timestamp": rec.timestamp,
                    "key": rec.key,
                    "fields": rec.fields,
                }
            )
            refs.append(f"{rec.source}:seq={rec.seq}")
        data: dict[str, Any] = {
            "records": rows,
            "count": len(rows),
            "anchor_seq": seq,
        }
        if not rows:
            data["hint"] = (
                f"no records near seq={seq}. The source may be empty, or "
                "the anchor is outside the seq range; call `query_records` "
                "with a small limit first to see what seqs exist."
            )
        return ToolResult(data=data, refs=refs)


def _clamp(value: Any, lo: int, hi: int) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        return lo
    return max(lo, min(v, hi))


__all__ = ["GetRecordsAroundTool"]
