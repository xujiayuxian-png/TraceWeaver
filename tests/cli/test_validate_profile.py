"""
Tests for `traceweaver validate-profile` (P1.5).

Covers:
- PASS on built-in open5gs_5gc profile
- FAIL when profile.yaml is missing
- FAIL when knowledge file is missing
- FAIL when tool class is not a Tool subclass
- FAIL when referenced module cannot be imported
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from traceweaver.cli.validate_profile import _validate_profile


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OPEN5GS_PROFILE = REPO_ROOT / "traceweaver" / "profiles" / "open5gs_5gc"


def test_validate_open5gs_profile_passes():
    """The shipped profile must validate cleanly."""
    errors = _validate_profile(OPEN5GS_PROFILE, verbose=False)
    assert errors == [], f"Expected no errors, got: {errors}"


def test_validate_missing_profile_yaml(tmp_path):
    """A directory without profile.yaml should fail gracefully."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    errors = _validate_profile(empty_dir, verbose=False)
    assert len(errors) >= 1
    assert any("Failed to load profile.yaml" in e for e in errors)


def _make_minimal_profile(tmp_path: Path, yaml_content: str, **extra_files: str) -> Path:
    """Helper: create a minimal profile dir with the given YAML + extra files."""
    pdir = tmp_path / "myprof"
    pdir.mkdir()
    (pdir / "profile.yaml").write_text(yaml_content, encoding="utf-8")
    for rel, content in extra_files.items():
        target = pdir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return pdir


def test_validate_missing_knowledge_file(tmp_path):
    """Declared knowledge file that doesn't exist must error."""
    yaml = textwrap.dedent("""
        name: testprof
        version: "0.1"
        source_config:
          pcap:
            fields: [ip.src]
        llm:
          system_prompt_file: prompt.md
          max_rounds: 5
        knowledge:
          - file: does_not_exist.md
            tags: [ref]
    """).strip()
    pdir = _make_minimal_profile(tmp_path, yaml, **{"prompt.md": "hello"})
    errors = _validate_profile(pdir, verbose=False)
    assert any("knowledge" in e.lower() and "not found" in e for e in errors), errors


def test_validate_bad_tool_class(tmp_path, monkeypatch):
    """A class that is not a Tool subclass must be flagged."""
    # Create a fake module with a non-Tool class and inject into sys.modules
    import sys
    import types
    fake_mod = types.ModuleType("fake_tool_mod")
    class NotATool:
        pass
    fake_mod.NotATool = NotATool
    monkeypatch.setitem(sys.modules, "fake_tool_mod", fake_mod)

    yaml = textwrap.dedent("""
        name: testprof
        version: "0.1"
        source_config:
          pcap:
            fields: [ip.src]
        llm:
          system_prompt_file: prompt.md
          max_rounds: 5
        tools:
          - module: fake_tool_mod
            class: NotATool
    """).strip()
    pdir = _make_minimal_profile(tmp_path, yaml, **{"prompt.md": "hello"})
    errors = _validate_profile(pdir, verbose=False)
    assert any("not a Tool subclass" in e for e in errors), errors


def test_validate_unknown_module(tmp_path):
    """An unimportable tool module must be reported, not crash."""
    yaml = textwrap.dedent("""
        name: testprof
        version: "0.1"
        source_config:
          pcap:
            fields: [ip.src]
        llm:
          system_prompt_file: prompt.md
          max_rounds: 5
        tools:
          - module: definitely.not.a.real.module
            class: SomeTool
    """).strip()
    pdir = _make_minimal_profile(tmp_path, yaml, **{"prompt.md": "hello"})
    errors = _validate_profile(pdir, verbose=False)
    assert any("Failed to load tool" in e for e in errors), errors


def test_validate_missing_enricher_function(tmp_path, monkeypatch):
    """An enricher function that doesn't exist in the module must fail."""
    import sys
    import types
    fake_mod = types.ModuleType("fake_enrich_mod")
    # no `enrich` function defined
    monkeypatch.setitem(sys.modules, "fake_enrich_mod", fake_mod)

    yaml = textwrap.dedent("""
        name: testprof
        version: "0.1"
        source_config:
          pcap:
            fields: [ip.src]
        llm:
          system_prompt_file: prompt.md
          max_rounds: 5
        enrichers:
          - module: fake_enrich_mod
            function: missing_fn
    """).strip()
    pdir = _make_minimal_profile(tmp_path, yaml, **{"prompt.md": "hello"})
    errors = _validate_profile(pdir, verbose=False)
    assert any("Enricher function not found" in e for e in errors), errors
