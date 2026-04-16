from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class VisibilityAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope_id: str
    completeness: str
    missing_segments: list[str] = Field(default_factory=list)
    weak_links: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
