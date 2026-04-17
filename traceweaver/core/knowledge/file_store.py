"""
FileKnowledgeStore: index a set of markdown files with keyword scoring.

Each file is split into blocks at top-of-file or at `## ` headings. A
query is lower-cased and split on whitespace; a block's score is the
sum of per-token occurrence counts (a dead-simple TF). Good enough for
M2 — we can swap in embeddings without touching the tool layer.

The store keeps all text in memory. Knowledge files are meant to be
kilobytes, not megabytes; a single 1 MB profile stays well under
Python's dict overhead.
"""

from __future__ import annotations

import re
from pathlib import Path

from traceweaver.core.knowledge.base import KnowledgeHit, KnowledgeStore
from traceweaver.core.profile.base import ProfileKnowledgeItem


_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_TOKEN_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_\-/.]*")


def _tokenize(text: str) -> list[str]:
    return [m.group(0).lower() for m in _TOKEN_RE.finditer(text)]


def _split_blocks(text: str) -> list[tuple[str, str]]:
    """
    Split a markdown document at `## ` headings.

    Returns a list of `(title, body)` pairs. Any text before the first
    heading becomes one leading block with title == "".
    """
    blocks: list[tuple[str, str]] = []
    positions: list[tuple[int, str]] = []
    for match in _HEADING_RE.finditer(text):
        positions.append((match.start(), match.group(1).strip()))

    if not positions:
        return [("", text.strip())]

    first_start, _ = positions[0]
    lead = text[:first_start].strip()
    if lead:
        blocks.append(("", lead))

    for i, (start, title) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        body = text[start:end]
        # Drop the heading line itself from the body.
        body = body.split("\n", 1)[1] if "\n" in body else ""
        blocks.append((title, body.strip()))

    return blocks


class _IndexedBlock:
    __slots__ = ("path", "title", "tags", "content", "tf")

    def __init__(
        self,
        *,
        path: Path,
        title: str,
        tags: list[str],
        content: str,
    ) -> None:
        self.path = path
        self.title = title
        self.tags = tags
        self.content = content
        self.tf: dict[str, int] = {}
        for tok in _tokenize(content):
            self.tf[tok] = self.tf.get(tok, 0) + 1
        for tok in _tokenize(title):
            # Heading terms are worth a bit more so queries with the exact
            # section name rank the section first.
            self.tf[tok] = self.tf.get(tok, 0) + 2


class FileKnowledgeStore(KnowledgeStore):
    def __init__(self, items: list[ProfileKnowledgeItem]) -> None:
        self._blocks: list[_IndexedBlock] = []
        self._sources: list[Path] = []
        for item in items:
            text = item.path.read_text(encoding="utf-8")
            self._sources.append(item.path)
            for title, body in _split_blocks(text):
                if not body:
                    continue
                self._blocks.append(
                    _IndexedBlock(
                        path=item.path,
                        title=title,
                        tags=list(item.tags),
                        content=body,
                    )
                )

    @classmethod
    def empty(cls) -> "FileKnowledgeStore":
        return cls(items=[])

    def list_sources(self) -> list[Path]:
        return list(self._sources)

    def search(
        self,
        query: str,
        *,
        tags: list[str] | None = None,
        limit: int = 3,
    ) -> list[KnowledgeHit]:
        tokens = _tokenize(query or "")
        if not tokens:
            return []

        tag_filter: set[str] | None = set(tags) if tags else None

        scored: list[tuple[float, _IndexedBlock]] = []
        for blk in self._blocks:
            if tag_filter is not None and not (tag_filter & set(blk.tags)):
                continue
            score = 0.0
            for tok in tokens:
                score += blk.tf.get(tok, 0)
            if score > 0:
                scored.append((score, blk))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        hits: list[KnowledgeHit] = []
        for score, blk in scored[: max(0, limit)]:
            hits.append(
                KnowledgeHit(
                    path=blk.path,
                    title=blk.title,
                    tags=list(blk.tags),
                    content=blk.content,
                    score=score,
                )
            )
        return hits


__all__ = ["FileKnowledgeStore"]
