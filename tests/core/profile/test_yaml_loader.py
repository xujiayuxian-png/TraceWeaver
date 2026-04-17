"""Tests for load_profile_from_dir."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from traceweaver.core.profile import load_profile_from_dir


FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "profiles" / "minimal"


def test_loads_minimal_fixture() -> None:
    prof = load_profile_from_dir(FIXTURE_DIR)
    assert prof.name == "minimal"
    assert prof.version == "1.0"
    assert "minimal test assistant" in prof.llm.system_prompt.lower()
    assert prof.llm.max_rounds == 6
    assert prof.llm.recommended_model == "openai/qwen/qwen3.5-9b"
    assert prof.source_config["pcap"]["display_filter"] == "ip"
    assert len(prof.knowledge) == 1
    assert prof.knowledge[0].path.is_absolute()
    assert "sample" in prof.knowledge[0].tags


def test_missing_directory(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        load_profile_from_dir(tmp_path / "nope")


def test_missing_profile_yaml(tmp_path) -> None:
    (tmp_path / "prompts").mkdir()
    with pytest.raises(FileNotFoundError):
        load_profile_from_dir(tmp_path)


def _write_minimal_profile(base: Path, *, overrides: dict | None = None) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    (base / "prompts").mkdir(exist_ok=True)
    (base / "prompts" / "system.md").write_text("hi", encoding="utf-8")
    yaml_text = (
        "name: tmp\n"
        "version: '0.1'\n"
        "llm:\n"
        "  system_prompt_file: prompts/system.md\n"
        "  max_rounds: 3\n"
    )
    if overrides and "yaml" in overrides:
        yaml_text = overrides["yaml"]
    (base / "profile.yaml").write_text(yaml_text, encoding="utf-8")
    return base


def test_requires_name(tmp_path) -> None:
    _write_minimal_profile(
        tmp_path,
        overrides={
            "yaml": (
                "version: '0.1'\n"
                "llm:\n"
                "  system_prompt_file: prompts/system.md\n"
            )
        },
    )
    with pytest.raises(ValueError, match="name"):
        load_profile_from_dir(tmp_path)


def test_requires_system_prompt_file(tmp_path) -> None:
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "profile.yaml").write_text(
        "name: tmp\nllm: {}\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="system_prompt_file"):
        load_profile_from_dir(tmp_path)


def test_system_prompt_file_must_exist(tmp_path) -> None:
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "profile.yaml").write_text(
        "name: tmp\nllm:\n  system_prompt_file: missing.md\n",
        encoding="utf-8",
    )
    with pytest.raises(FileNotFoundError):
        load_profile_from_dir(tmp_path)


def test_response_schema_file(tmp_path) -> None:
    base = _write_minimal_profile(tmp_path)
    schema_dir = base / "schema"
    schema_dir.mkdir()
    (schema_dir / "diag.json").write_text(
        json.dumps({"type": "object", "required": ["answer"]}),
        encoding="utf-8",
    )
    (base / "profile.yaml").write_text(
        "name: tmp\n"
        "version: '0.1'\n"
        "llm:\n"
        "  system_prompt_file: prompts/system.md\n"
        "  response_schema_file: schema/diag.json\n",
        encoding="utf-8",
    )
    prof = load_profile_from_dir(base)
    assert prof.llm.response_schema == {"type": "object", "required": ["answer"]}


def test_response_schema_file_bad_json(tmp_path) -> None:
    base = _write_minimal_profile(tmp_path)
    (base / "schema").mkdir()
    (base / "schema" / "diag.json").write_text("{not json", encoding="utf-8")
    (base / "profile.yaml").write_text(
        "name: tmp\n"
        "llm:\n"
        "  system_prompt_file: prompts/system.md\n"
        "  response_schema_file: schema/diag.json\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="not valid JSON"):
        load_profile_from_dir(base)


def test_rejects_path_escape(tmp_path) -> None:
    _write_minimal_profile(tmp_path)
    (tmp_path / "profile.yaml").write_text(
        "name: tmp\n"
        "llm:\n"
        "  system_prompt_file: ../secrets.md\n",
        encoding="utf-8",
    )
    (tmp_path.parent / "secrets.md").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="escapes profile root"):
        load_profile_from_dir(tmp_path)
