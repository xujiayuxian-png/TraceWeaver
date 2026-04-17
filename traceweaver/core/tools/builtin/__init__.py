"""
Built-in tools shipped by core.

They depend only on the public `ToolContext` fields (`source_handle`,
`knowledge_store`) so any profile / source combination can adopt them
without glue code.

`register_builtin_tools(registry)` is the single entry point; the kernel
and the M2 smoke script both call it.
"""

from traceweaver.core.tools.builtin.get_records_around import GetRecordsAroundTool
from traceweaver.core.tools.builtin.query_records import QueryRecordsTool
from traceweaver.core.tools.builtin.search_knowledge import SearchKnowledgeTool
from traceweaver.core.tools.registry import ToolRegistry


def register_builtin_tools(registry: ToolRegistry) -> None:
    """Register the three universal built-in tools on an empty registry."""
    registry.register_all(
        [
            QueryRecordsTool(),
            GetRecordsAroundTool(),
            SearchKnowledgeTool(),
        ]
    )


__all__ = [
    "GetRecordsAroundTool",
    "QueryRecordsTool",
    "SearchKnowledgeTool",
    "register_builtin_tools",
]
