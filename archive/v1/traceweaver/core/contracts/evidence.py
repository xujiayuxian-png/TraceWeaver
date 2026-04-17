from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    scope_id: str = ""
    source_type: str
    source_name: str
    summary: str
    frame_numbers: list[int] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)
    supports: list[str] = Field(default_factory=list)
    contradicts: list[str] = Field(default_factory=list)
