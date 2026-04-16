from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AnalysisOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_filter: str | None = None
    decode_as: list[str] = Field(default_factory=list)
    limit: int | None = None
