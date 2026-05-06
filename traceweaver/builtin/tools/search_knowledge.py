"""search_knowledge: profile knowledge-base lookup."""
from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field
from traceweaver.core.protocols import Tool, ToolContext, ToolResult, ToolSpec

_MAX_LIMIT = 10


class _SearchKnowledgeInput(BaseModel):
    query: str = Field(description="Keyword query")
    tags: list[str] | None = Field(default=None, description="Optional tag filter")
    limit: int = Field(default=3, ge=1, le=_MAX_LIMIT, description="Max hits (1-10)")


class SearchKnowledgeTool(Tool):
    spec = ToolSpec.from_pydantic(
        _SearchKnowledgeInput,
        name="search_knowledge",
        description="Search the profile's knowledge base for documents matching a keyword query.",
    )

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        store = ctx.knowledge_store
        if store is None:
            return ToolResult(data={"hits": [], "count": 0, "hint": "no knowledge base"})

        query = kwargs.get("query")
        if not isinstance(query, str) or not query.strip():
            return ToolResult(data={"hits": [], "count": 0, "hint": "query required"})

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
            rows.append({"content": hit.content, "title": hit.title, "score": hit.score})

        data: dict[str, Any] = {"hits": rows, "count": len(rows)}
        if not rows:
            data["hint"] = f"no knowledge entries match query {query!r}; do not retry with same query"
        return ToolResult(data=data)

__all__ = ["SearchKnowledgeTool"]
