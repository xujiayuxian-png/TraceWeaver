"""search_knowledge: profile knowledge-base lookup."""
from __future__ import annotations
from typing import Any
from traceweaver.core.protocols import Tool, ToolContext, ToolResult, ToolSpec

_MAX_LIMIT = 10

class SearchKnowledgeTool(Tool):
    spec = ToolSpec(
        name="search_knowledge",
        description="Search the profile's knowledge base for documents matching a keyword query.",
        parameters_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Keyword query"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional tag filter"},
                "limit": {"type": "integer", "description": "Max hits (1-10)", "minimum": 1, "maximum": _MAX_LIMIT},
            },
            "required": ["query"],
        },
    )

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        store = ctx.knowledge_store
        if store is None:
            return ToolResult(data={"hits": [], "count": 0, "hint": "no knowledge base"})

        query = kwargs.get("query")
        if not isinstance(query, str) or not query.strip():
            return ToolResult(data={"hits": [], "count": 0, "hint": "query must be non-empty string"})

        tags = kwargs.get("tags")
        limit_raw = kwargs.get("limit")
        try:
            limit = int(limit_raw) if limit_raw is not None else 3
        except (TypeError, ValueError):
            limit = 3
        limit = max(1, min(limit, _MAX_LIMIT))

        hits = store.search(query, tags=tags, top_k=limit)
        rows: list[dict[str, Any]] = []
        for hit in hits:
            rows.append({"content": hit.content, "score": hit.score})

        data: dict[str, Any] = {"hits": rows, "count": len(rows)}
        if not rows:
            data["hint"] = f"no knowledge entries match query {query!r}"
        return ToolResult(data=data)

__all__ = ["SearchKnowledgeTool"]
