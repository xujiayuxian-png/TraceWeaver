"""query_records: filtered / projected / paginated scan of the source."""
from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field
from traceweaver.core.protocols import Tool, ToolContext, ToolResult, ToolSpec

_DEFAULT_LIMIT = 50
_MAX_LIMIT = 500


class QueryRecordsArgs(BaseModel):
    """Arguments for query_records tool."""
    filter: dict[str, Any] | None = Field(
        default=None, description="Flat dict of equality constraints"
    )
    fields: list[str] | None = Field(
        default=None, description="Project fields to these keys"
    )
    limit: int = Field(
        default=_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT, description="Max records (1-500)"
    )


class QueryRecordsTool(Tool):
    spec = ToolSpec.from_pydantic(
        QueryRecordsArgs,
        name="query_records",
        description="Scan the loaded source for records matching an equality filter.",
    )

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        if ctx.source_handle is None:
            return ToolResult(data={"records": [], "count": 0, "hint": "no source loaded"})

        try:
            args = QueryRecordsArgs.model_validate(kwargs)
        except Exception as e:
            return ToolResult(data={"records": [], "count": 0, "hint": f"invalid arguments: {e}"})
        flt = args.filter
        fields = args.fields
        limit = args.limit

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
