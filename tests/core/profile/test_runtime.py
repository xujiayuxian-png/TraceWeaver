"""Tests for traceweaver.core.profile.runtime."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from traceweaver.core.profile.base import (
    Profile,
    ProfileEnricherSpec,
    ProfileLLMConfig,
)
from traceweaver.core.profile.runtime import (
    build_knowledge_store,
    ingest_for_profile,
    resolve_enrichers,
    wrap_handle_for_profile,
)
from traceweaver.core.profile.yaml_loader import load_profile_from_dir
from traceweaver.core.protocols import Record, SourceSpec
from traceweaver.builtin.sources.enriched import EnrichedSourceHandle
from traceweaver.builtin.sources.fake import FakeSource


# ---- shared helpers ----

def _bare_profile(tmp_path: Path, enrichers: list[ProfileEnricherSpec] | None = None) -> Profile:
    (tmp_path / "system.md").write_text("SYS", encoding="utf-8")
    return Profile(
        name="t",
        root=tmp_path,
        llm=ProfileLLMConfig(system_prompt="SYS"),
        enrichers=list(enrichers or []),
    )


def _make_handle(records: list[Record]):
    return FakeSource().ingest(
        SourceSpec(kind="fake", uri="memory://t", options={"records_object": records})
    )


def _rec(seq: int, **fields) -> Record:
    return Record(
        source="fake",
        timestamp=1000.0 + seq,
        seq=seq,
        key=fields.pop("key", f"k{seq}"),
        fields=fields,
    )


# ---- resolve_enrichers ----

def test_resolve_enrichers_imports_callable() -> None:
    spec = ProfileEnricherSpec(
        module="tests.core.profile._enricher_fixture",
        function="add_hi",
    )
    fns = resolve_enrichers([spec])
    out = fns[0](_rec(1))
    assert out.fields.get("hi") == "there"


def test_resolve_enrichers_missing_module() -> None:
    with pytest.raises(ImportError):
        resolve_enrichers(
            [ProfileEnricherSpec(module="no.such.module", function="x")]
        )


def test_resolve_enrichers_missing_attr(tmp_path: Path) -> None:
    with pytest.raises(AttributeError):
        resolve_enrichers(
            [
                ProfileEnricherSpec(
                    module="tests.core.profile._enricher_fixture",
                    function="does_not_exist",
                )
            ]
        )


def test_resolve_enrichers_non_callable() -> None:
    with pytest.raises(TypeError):
        resolve_enrichers(
            [
                ProfileEnricherSpec(
                    module="tests.core.profile._enricher_fixture",
                    function="NOT_CALLABLE",
                )
            ]
        )


# ---- wrap_handle_for_profile ----

def test_wrap_returns_raw_handle_when_no_enrichers(tmp_path: Path) -> None:
    p = _bare_profile(tmp_path)
    inner = _make_handle([_rec(1)])
    wrapped = wrap_handle_for_profile(p, inner)
    assert wrapped is inner


def test_wrap_returns_enriched_handle_when_enrichers_declared(
    tmp_path: Path,
) -> None:
    p = _bare_profile(
        tmp_path,
        enrichers=[
            ProfileEnricherSpec(
                module="tests.core.profile._enricher_fixture",
                function="add_hi",
            )
        ],
    )
    inner = _make_handle([_rec(1)])
    wrapped = wrap_handle_for_profile(p, inner)
    assert isinstance(wrapped, EnrichedSourceHandle)
    records = list(wrapped.iter_records())
    assert records[0].fields.get("hi") == "there"


def test_extra_enrichers_appended_after_profile_chain(tmp_path: Path) -> None:
    p = _bare_profile(
        tmp_path,
        enrichers=[
            ProfileEnricherSpec(
                module="tests.core.profile._enricher_fixture",
                function="add_hi",
            )
        ],
    )
    inner = _make_handle([_rec(1)])

    def tag(r: Record) -> Record:
        new = dict(r.fields)
        new["tagged"] = True
        return r.model_copy(update={"fields": new})

    wrapped = wrap_handle_for_profile(p, inner, extra_enrichers=[tag])
    records = list(wrapped.iter_records())
    assert records[0].fields["hi"] == "there"
    assert records[0].fields["tagged"] is True


# ---- ingest_for_profile ----

def test_ingest_for_profile_builds_and_wraps(tmp_path: Path) -> None:
    from traceweaver.core.source.registry import SourceRegistry
    from traceweaver.builtin.sources.fake import FakeSource

    p = _bare_profile(
        tmp_path,
        enrichers=[
            ProfileEnricherSpec(
                module="tests.core.profile._enricher_fixture",
                function="add_hi",
            )
        ],
    )
    spec = SourceSpec(
        kind="fake",
        uri="memory://t",
        options={"records_object": [_rec(1), _rec(2)]},
    )
    registry = SourceRegistry()
    registry.register(FakeSource())
    handle = ingest_for_profile(p, spec, registry=registry)
    assert isinstance(handle, EnrichedSourceHandle)
    assert all(r.fields.get("hi") == "there" for r in handle.iter_records())


# ---- build_knowledge_store ----

def test_build_knowledge_store_none_when_empty(tmp_path: Path) -> None:
    p = _bare_profile(tmp_path)
    assert build_knowledge_store(p) is None


def test_build_knowledge_store_indexes_items(tmp_path: Path) -> None:
    # Build a real profile on disk so knowledge items resolve.
    kn_dir = tmp_path / "knowledge"
    kn_dir.mkdir()
    (kn_dir / "sample.md").write_text(
        "## Foo\nhello world\n", encoding="utf-8"
    )
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "system.md").write_text("SYS", encoding="utf-8")
    (tmp_path / "profile.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "t",
                "llm": {"system_prompt_file": "prompts/system.md"},
                "knowledge": [{"file": "knowledge/sample.md"}],
            }
        ),
        encoding="utf-8",
    )
    profile = load_profile_from_dir(tmp_path)

    store = build_knowledge_store(profile)
    assert store is not None
    hits = store.search("hello")
    assert hits, "expected at least one knowledge hit"


# ---- profile.yaml: enrichers section ----

def test_yaml_loader_parses_enrichers(tmp_path: Path) -> None:
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "system.md").write_text("S", encoding="utf-8")
    (tmp_path / "profile.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "p",
                "llm": {"system_prompt_file": "prompts/system.md"},
                "enrichers": [
                    {
                        "module": "tests.core.profile._enricher_fixture",
                        "function": "add_hi",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    p = load_profile_from_dir(tmp_path)
    assert len(p.enrichers) == 1
    assert p.enrichers[0].module == "tests.core.profile._enricher_fixture"
    assert p.enrichers[0].function == "add_hi"


def test_yaml_loader_rejects_bad_enricher(tmp_path: Path) -> None:
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "system.md").write_text("S", encoding="utf-8")
    (tmp_path / "profile.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "p",
                "llm": {"system_prompt_file": "prompts/system.md"},
                "enrichers": [{"module": "x"}],  # missing function
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="function"):
        load_profile_from_dir(tmp_path)
