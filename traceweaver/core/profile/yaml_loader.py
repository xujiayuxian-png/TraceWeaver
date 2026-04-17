"""
`load_profile_from_dir(path) -> Profile`.

Reads `profile.yaml` and resolves every file reference relative to the
profile root. No network, no tool imports; this is a pure data loader.

Error policy: a malformed profile raises `ValueError` with a message
that names the offending field. The CLI layer will surface these to the
user directly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from traceweaver.core.profile.base import (
    Profile,
    ProfileKnowledgeItem,
    ProfileLLMConfig,
)


def load_profile_from_dir(path: Path | str) -> Profile:
    root = Path(path).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"profile directory not found: {root}")

    yaml_path = root / "profile.yaml"
    if not yaml_path.is_file():
        raise FileNotFoundError(f"profile.yaml missing under {root}")

    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{yaml_path} must contain a mapping at top level")

    name = raw.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError(f"{yaml_path}: 'name' is required and must be a non-empty string")

    llm_cfg = _build_llm(raw.get("llm") or {}, root, yaml_path)

    knowledge_items = _build_knowledge(raw.get("knowledge") or [], root, yaml_path)

    source_config = raw.get("source_config") or {}
    if not isinstance(source_config, dict):
        raise ValueError(f"{yaml_path}: 'source_config' must be a mapping")

    scope = raw.get("scope") or {}
    if not isinstance(scope, dict):
        raise ValueError(f"{yaml_path}: 'scope' must be a mapping")

    applies = raw.get("applies_to_sources") or []
    if not isinstance(applies, list) or not all(isinstance(s, str) for s in applies):
        raise ValueError(f"{yaml_path}: 'applies_to_sources' must be a list of strings")

    tools_decl = raw.get("tools") or []
    if not isinstance(tools_decl, list):
        raise ValueError(f"{yaml_path}: 'tools' must be a list")

    return Profile(
        name=name,
        version=str(raw.get("version", "0.0")),
        display_name=str(raw.get("display_name", "") or ""),
        description=str(raw.get("description", "") or ""),
        root=root,
        applies_to_sources=list(applies),
        source_config=dict(source_config),
        scope=dict(scope),
        llm=llm_cfg,
        knowledge=knowledge_items,
        tools=list(tools_decl),
    )


def _build_llm(block: dict[str, Any], root: Path, yaml_path: Path) -> ProfileLLMConfig:
    prompt_file = block.get("system_prompt_file")
    if not isinstance(prompt_file, str) or not prompt_file:
        raise ValueError(f"{yaml_path}: 'llm.system_prompt_file' is required")
    prompt_path = (root / prompt_file).resolve()
    if root not in prompt_path.parents and prompt_path != root:
        raise ValueError(
            f"{yaml_path}: system_prompt_file {prompt_file!r} escapes profile root"
        )
    if not prompt_path.is_file():
        raise FileNotFoundError(
            f"{yaml_path}: system_prompt_file not found: {prompt_path}"
        )
    system_prompt = prompt_path.read_text(encoding="utf-8")

    response_schema: dict[str, Any] | None = None
    schema_file = block.get("response_schema_file")
    if isinstance(schema_file, str) and schema_file:
        schema_path = (root / schema_file).resolve()
        if not schema_path.is_file():
            raise FileNotFoundError(
                f"{yaml_path}: response_schema_file not found: {schema_path}"
            )
        try:
            response_schema = json.loads(schema_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{yaml_path}: response_schema_file {schema_path} is not valid JSON: {exc}"
            ) from exc
        if not isinstance(response_schema, dict):
            raise ValueError(
                f"{yaml_path}: response_schema_file {schema_path} must be a JSON object"
            )

    max_rounds = block.get("max_rounds", 5)
    if not isinstance(max_rounds, int) or max_rounds < 1:
        raise ValueError(f"{yaml_path}: 'llm.max_rounds' must be a positive integer")

    recommended_model = block.get("recommended_model")
    if recommended_model is not None and not isinstance(recommended_model, str):
        raise ValueError(f"{yaml_path}: 'llm.recommended_model' must be a string if set")

    return ProfileLLMConfig(
        system_prompt=system_prompt,
        max_rounds=max_rounds,
        response_schema=response_schema,
        recommended_model=recommended_model,
    )


def _build_knowledge(
    block: list[Any], root: Path, yaml_path: Path
) -> list[ProfileKnowledgeItem]:
    items: list[ProfileKnowledgeItem] = []
    for idx, entry in enumerate(block):
        if not isinstance(entry, dict):
            raise ValueError(
                f"{yaml_path}: knowledge[{idx}] must be a mapping, got {type(entry).__name__}"
            )
        file_rel = entry.get("file")
        if not isinstance(file_rel, str) or not file_rel:
            raise ValueError(f"{yaml_path}: knowledge[{idx}].file is required")
        fpath = (root / file_rel).resolve()
        if root not in fpath.parents:
            raise ValueError(
                f"{yaml_path}: knowledge[{idx}].file {file_rel!r} escapes profile root"
            )
        if not fpath.is_file():
            raise FileNotFoundError(
                f"{yaml_path}: knowledge[{idx}].file not found: {fpath}"
            )
        tags = entry.get("tags") or []
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            raise ValueError(
                f"{yaml_path}: knowledge[{idx}].tags must be a list of strings"
            )
        items.append(ProfileKnowledgeItem(path=fpath, tags=list(tags)))
    return items


__all__ = ["load_profile_from_dir"]
