"""FileKnowledgeStore: index markdown files with keyword scoring."""
from __future__ import annotations
import re
from pathlib import Path
from typing import Any
from traceweaver.core.protocols import KnowledgeHit, KnowledgeStore

_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_TOKEN_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_\-/.]*")

def _tokenize(text: str) -> list[str]:
    return [m.group(0).lower() for m in _TOKEN_RE.finditer(text)]

def _split_blocks(text: str) -> list[tuple[str, str]]:
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
        body = body.split("\n", 1)[1] if "\n" in body else ""
        blocks.append((title, body.strip()))
    return blocks

class _IndexedBlock:
    __slots__ = ("path", "title", "tags", "content", "tf")

    def __init__(self, *, path: Path, title: str, tags: list[str], content: str) -> None:
        self.path = path
        self.title = title
        self.tags = tags
        self.content = content
        self.tf: dict[str, int] = {}
        for tok in _tokenize(content):
            self.tf[tok] = self.tf.get(tok, 0) + 1
        for tok in _tokenize(title):
            self.tf[tok] = self.tf.get(tok, 0) + 2

class FileKnowledgeStore(KnowledgeStore):
    def __init__(self, items: list[Any]) -> None:  # items: ProfileKnowledgeItem list
        self._blocks: list[_IndexedBlock] = []
        self._sources: list[Path] = []
        for item in items:
            path = Path(item.path) if hasattr(item, 'path') else Path(item["path"])
            text = path.read_text(encoding="utf-8")
            self._sources.append(path)
            tags = list(item.tags) if hasattr(item, 'tags') else list(item.get("tags", []))
            for title, body in _split_blocks(text):
                if not body:
                    continue
                self._blocks.append(_IndexedBlock(path=path, title=title, tags=tags, content=body))

    @staticmethod
    def empty() -> "FileKnowledgeStore":
        """Return an empty knowledge store for testing."""
        return FileKnowledgeStore(items=[])

    def list_sources(self) -> list[Path]:
        """Return list of source file paths."""
        return list(self._sources)

    def search(self, query: str, *, top_k: int = 5, limit: int | None = None, tags: list[str] | None = None) -> list[KnowledgeHit]:
        """Search knowledge store. `limit` is alias for `top_k` for backward compatibility."""
        effective_top_k = limit if limit is not None else top_k
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
        for score, blk in scored[:max(0, effective_top_k)]:
            hits.append(KnowledgeHit(content=blk.content, title=blk.title, score=score))
        return hits

__all__ = ["FileKnowledgeStore"]
