"""
KnowledgeStore abstraction.

Deliberately minimal: the `search` contract returns structured
`KnowledgeHit` results so tool implementations can project whatever
shape the LLM wants without re-parsing on each call.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeHit(BaseModel):
    """One block from a knowledge document that matched a query."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    path: Path
    """Source file (absolute)."""

    title: str = ""
    """Heading of the block, if any. Empty for whole-document hits."""

    tags: list[str] = Field(default_factory=list)
    """Tags declared in profile.yaml for the source file."""

    content: str = ""
    """Text of the block (potentially truncated by the store)."""

    score: float = 0.0
    """Implementation-specific relevance score; higher is better."""


class KnowledgeStore(ABC):
    @abstractmethod
    def list_sources(self) -> list[Path]:
        """Return the files this store indexes."""

    @abstractmethod
    def search(
        self,
        query: str,
        *,
        tags: list[str] | None = None,
        limit: int = 3,
    ) -> list[KnowledgeHit]:
        """
        Rank blocks by `query` (and optional tag filter) and return the
        top `limit`. Empty query or no matches -> []; tools decide how
        to tell the LLM "no hits" (usually with an explicit hint in the
        `ToolResult.data`).
        """


__all__ = ["KnowledgeHit", "KnowledgeStore"]
