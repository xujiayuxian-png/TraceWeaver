"""
`search_knowledge`: profile knowledge-base lookup.

The LLM passes a query (and optional tag filter); the store scores its
indexed blocks and returns the top matches. When nothing matches we
include an explicit `hint` in `data` so the model doesn't spin in a
search loop (this is the M1 lesson hard-coded into the contract).
"""

from __future__ import annotations

from typing import Any

from traceweaver.core.tools.base import Tool, ToolContext, ToolResult, ToolSpec


_MAX_LIMIT = 10


class SearchKnowledgeTool(Tool):
    spec = ToolSpec(
        name="search_knowledge",
        description=(
            "Search the profile's knowledge base for documents matching a "
            "keyword query. Returns `{hits: [...], count, hint?}` where each "
            "hit has `path`, `title`, `tags`, `content`, `score`. Use `tags` "
            "to restrict to a topic area; an empty result set will include a "
            "`hint` — do NOT keep retrying the same query."
        ),
        parameters_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword query (whitespace-separated tokens).",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional tag filter; a hit must carry at least one of these tags.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum hits to return (1-10).",
                    "minimum": 1,
                    "maximum": _MAX_LIMIT,
                },
            },
            "required": ["query"],
        },
    )

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        store = ctx.knowledge_store
        if store is None:
            return ToolResult(
                data={
                    "hits": [],
                    "count": 0,
                    "hint": "this profile has no knowledge base; rely on the records returned by `query_records` instead of retrying.",
                }
            )

        query = kwargs.get("query")
        if not isinstance(query, str) or not query.strip():
            return ToolResult(
                data={
                    "hits": [],
                    "count": 0,
                    "hint": "`query` is required and must be a non-empty string.",
                }
            )
        tags = kwargs.get("tags")
        if tags is not None and not isinstance(tags, list):
            return ToolResult(
                data={
                    "hits": [],
                    "count": 0,
                    "hint": f"`tags` must be an array of strings; got {type(tags).__name__}.",
                }
            )
        limit_raw = kwargs.get("limit")
        try:
            limit = int(limit_raw) if limit_raw is not None else 3
        except (TypeError, ValueError):
            limit = 3
        limit = max(1, min(limit, _MAX_LIMIT))

        hits = store.search(query, tags=tags, limit=limit)
        rows: list[dict[str, Any]] = []
        for hit in hits:
            rows.append(
                {
                    "path": str(hit.path),
                    "title": hit.title,
                    "tags": hit.tags,
                    "content": hit.content,
                    "score": hit.score,
                }
            )

        data: dict[str, Any] = {"hits": rows, "count": len(rows)}
        if not rows:
            data["hint"] = (
                f"no knowledge entries match the query {query!r}"
                + (f" with tags {tags!r}" if tags else "")
                + ". Do not retry with variations; answer from the records "
                "the tools have already returned."
            )
        return ToolResult(data=data)


__all__ = ["SearchKnowledgeTool"]
