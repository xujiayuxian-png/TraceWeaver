"""
KnowledgeStore: the search surface exposed to tools (and to the built-in
`search_knowledge` tool specifically).

M2 ships a file-backed implementation that indexes each knowledge file
as one document, optionally split into section blocks at markdown
`##`-level headings. The same abstraction can later wrap an embedding
store without tool-side changes.
"""

from traceweaver.core.knowledge.base import (
    KnowledgeHit,
    KnowledgeStore,
)
from traceweaver.core.knowledge.file_store import FileKnowledgeStore

__all__ = [
    "FileKnowledgeStore",
    "KnowledgeHit",
    "KnowledgeStore",
]
