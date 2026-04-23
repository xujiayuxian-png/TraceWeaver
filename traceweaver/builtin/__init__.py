"""Builtin implementations - register these explicitly."""
from traceweaver.builtin.sources.pcap import PcapSource
from traceweaver.builtin.sources.fake import FakeSource
from traceweaver.builtin.tools.query_records import QueryRecordsTool
from traceweaver.builtin.tools.get_records_around import GetRecordsAroundTool
from traceweaver.builtin.tools.search_knowledge import SearchKnowledgeTool


def register_builtin_sources(registry) -> None:
    """Register pcap and fake sources on an empty registry."""
    registry.register(PcapSource())
    registry.register(FakeSource())


def register_builtin_tools(registry) -> None:
    """Register the three universal built-in tools on an empty registry."""
    registry.register(QueryRecordsTool())
    registry.register(GetRecordsAroundTool())
    registry.register(SearchKnowledgeTool())


__all__ = [
    "register_builtin_sources",
    "register_builtin_tools",
    "PcapSource",
    "FakeSource",
    "QueryRecordsTool",
    "GetRecordsAroundTool",
    "SearchKnowledgeTool",
]
