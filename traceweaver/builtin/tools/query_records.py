"""query_records: filtered / projected / paginated scan of the source."""
from __future__ import annotations
from typing import Any
from traceweaver.core.protocols import Tool, ToolContext, ToolResult, ToolSpec

_DEFAULT_LIMIT = 50
_MAX_LIMIT = 500

class QueryRecordsTool(Tool):
    spec = ToolSpec(
        name="query_records",
        description="Scan the loaded source for records matching an equality filter.",
        parameters_schema={
            "type": "object",
            "properties": {
                "filter": {"type": "object", "description": "Flat dict of equality constraints"},
                "fields": {"type": "array", "items": {"type": "string"}, "description": "Project fields to these keys"},
                "limit": {"type": "integer", "description": "Max records (1-500)", "minimum": 1, "maximum": _MAX_LIMIT},
            },
            "required": [],
        },
    )

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        if ctx.source_handle is None:
            return ToolResult(data={"records": [], "count": 0, "hint": "no source loaded"})

        flt = kwargs.get("filter")
        if flt is not None and not isinstance(flt, dict):
            return ToolResult(data={"records": [], "count": 0, "hint": "filter must be an object"})
        fields = kwargs.get("fields")
        limit = kwargs.get("limit")
        if limit is None:
            limit = _DEFAULT_LIMIT
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = _DEFAULT_LIMIT
        limit = max(1, min(limit, _MAX_LIMIT))

        collected: list[dict[str, Any]] = []
        refs: list[str] = []
        truncated = False
        iterator = ctx.source_handle.iter_records(filter=flt, fields=fields, limit=limit + 1)
        for rec in iterator:
            if len(collected) >= limit:
                truncated = True
                break
            collected.append({"source": rec.source, "seq": rec.seq, "timestamp": rec.timestamp, "key": rec.key, "fields": rec.fields})
            refs.append(f"{rec.source}:seq={rec.seq}")

        data: dict[str, Any] = {"records": collected, "count": len(collected), "truncated": truncated}
        if not collected:
            data["hint"] = "no records match this filter"
        return ToolResult(data=data, refs=refs, truncated=truncated)

__all__ = ["QueryRecordsTool"]
