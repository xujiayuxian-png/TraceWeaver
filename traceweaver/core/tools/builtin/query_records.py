"""
`query_records`: filtered / projected / paginated scan of the source.

Mirrors the hot path every profile eventually needs: "give me the
records where field X == Y, showing only these columns, up to N rows".

Behavior when `ctx.source_handle` is None: the tool returns a structured
error message instead of raising, so the LLM can recover by calling a
different tool (this keeps the kernel's tool-result contract uniform).
"""

from __future__ import annotations

from typing import Any

from traceweaver.core.tools.base import Tool, ToolContext, ToolResult, ToolSpec


_DEFAULT_LIMIT = 50
_MAX_LIMIT = 500


class QueryRecordsTool(Tool):
    spec = ToolSpec(
        name="query_records",
        description=(
            "Scan the loaded source for records matching an equality filter. "
            "`filter` is a flat JSON object (NOT nested, NOT a string) keyed "
            "by top-level columns (source, seq, key) or by protocol fields "
            "declared by the profile (e.g. event, ngap.RAN_UE_NGAP_ID). "
            "Example: {\"filter\": {\"event\": \"REGISTRATION_REJECT\"}}. "
            "Use `fields` to project inner record.fields keys (top-level "
            "columns like seq/key are always returned). `limit` caps the "
            "rows returned (default 50, max 500). Returns "
            "`{records: [...], count, truncated, hint?}` where each record "
            "has top-level `source`, `seq`, `timestamp`, `key`, and nested `fields`."
        ),
        parameters_schema={
            "type": "object",
            "properties": {
                "filter": {
                    "type": "object",
                    "description": "Flat dict of equality constraints. Keys are field names; values are strings, ints or floats.",
                    "additionalProperties": True,
                },
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Project the returned records' fields down to these keys. Unknown keys are silently dropped.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum records to return (1-500).",
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
                data={
                    "records": [],
                    "count": 0,
                    "hint": "no source is loaded in this context; the kernel must provide source_handle.",
                },
            )

        flt = kwargs.get("filter") or None
        if flt is not None and not isinstance(flt, dict):
            return ToolResult(
                data={
                    "records": [],
                    "count": 0,
                    "hint": f"`filter` must be an object; got {type(flt).__name__}.",
                },
            )

        fields = kwargs.get("fields")
        if fields is not None and not isinstance(fields, list):
            return ToolResult(
                data={
                    "records": [],
                    "count": 0,
                    "hint": f"`fields` must be an array of strings; got {type(fields).__name__}.",
                },
            )

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
        iterator = ctx.source_handle.iter_records(
            filter=flt, fields=fields, limit=limit + 1
        )
        truncated = False
        for rec in iterator:
            if len(collected) >= limit:
                truncated = True
                break
            collected.append(
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
            "records": collected,
            "count": len(collected),
            "truncated": truncated,
        }
        if not collected:
            data["hint"] = (
                "no records match this filter. Try relaxing the constraints "
                "or calling `query_records` with an empty filter and small limit "
                "to inspect the source's actual field values."
            )
        return ToolResult(data=data, refs=refs, truncated=truncated)


__all__ = ["QueryRecordsTool"]
