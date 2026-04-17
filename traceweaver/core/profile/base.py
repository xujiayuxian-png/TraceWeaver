"""
Profile data model (pure values; no I/O here).

Keep this module dependency-free so `Profile` can be used in tests
without touching the filesystem.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProfileLLMConfig(BaseModel):
    """LLM-facing configuration resolved from `profile.yaml:llm`."""

    model_config = ConfigDict(frozen=True)

    system_prompt: str
    """Already-loaded system prompt text."""

    max_rounds: int = 5
    response_schema: dict[str, Any] | None = None
    recommended_model: str | None = None


class ProfileKnowledgeItem(BaseModel):
    """One file in a profile's knowledge base."""

    model_config = ConfigDict(frozen=True)

    path: Path
    tags: list[str] = Field(default_factory=list)


class Profile(BaseModel):
    """
    A fully-resolved profile. All file paths are absolute; all referenced
    text (system prompt, response schema) is already loaded.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    name: str
    version: str = "0.0"
    display_name: str = ""
    description: str = ""

    root: Path
    """Absolute path to the profile directory."""

    applies_to_sources: list[str] = Field(default_factory=list)

    source_config: dict[str, dict[str, Any]] = Field(default_factory=dict)
    """Map `kind -> options` understood by that source's `ingest`."""

    scope: dict[str, Any] = Field(default_factory=dict)
    """Passed through verbatim; interpreted by scope splitter (future M)."""

    llm: ProfileLLMConfig

    knowledge: list[ProfileKnowledgeItem] = Field(default_factory=list)

    tools: list[dict[str, Any]] = Field(default_factory=list)
    """
    Raw `{module, class, ...}` entries. Tool loading happens in a later
    M; we preserve the declaration here so profile round-trips stay
    faithful.
    """


__all__ = ["Profile", "ProfileKnowledgeItem", "ProfileLLMConfig"]
