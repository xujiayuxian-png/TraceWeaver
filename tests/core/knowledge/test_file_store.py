"""Tests for FileKnowledgeStore."""

from __future__ import annotations

from pathlib import Path

from traceweaver.builtin.knowledge.file_store import FileKnowledgeStore
from traceweaver.core.profile.base import ProfileKnowledgeItem


FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "profiles"
    / "minimal"
    / "knowledge"
    / "sample.md"
)


def _store() -> FileKnowledgeStore:
    return FileKnowledgeStore(
        items=[ProfileKnowledgeItem(path=FIXTURE, tags=["sample", "test"])]
    )


def test_list_sources() -> None:
    store = _store()
    assert store.list_sources() == [FIXTURE]


def test_empty_query_returns_nothing() -> None:
    assert _store().search("") == []


def test_search_ranks_section_title_higher() -> None:
    hits = _store().search("registration reject")
    assert len(hits) >= 1
    assert hits[0].title == "Registration Reject"


def test_search_finds_substring_terms() -> None:
    hits = _store().search("PDU session")
    titles = [h.title for h in hits]
    assert "PDU Session" in titles


def test_tag_filter_narrow() -> None:
    store = _store()
    hits = store.search("cause code", tags=["sample"])
    assert len(hits) >= 1
    hits_empty = store.search("cause code", tags=["does-not-exist"])
    assert hits_empty == []


def test_no_match_returns_empty_list() -> None:
    assert _store().search("zzz-unlikely-token-xxx") == []


def test_limit_respected() -> None:
    store = _store()
    hits = store.search("cause code PDU session", limit=1)
    assert len(hits) == 1


def test_empty_store() -> None:
    store = FileKnowledgeStore.empty()
    assert store.list_sources() == []
    assert store.search("anything") == []
