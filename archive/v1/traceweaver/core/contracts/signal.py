from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DiagnosticSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signal_id: str
    name: str
    scope_id: str
    source: str = ""
    category: str = ""
    confidence: str = "high"
    summary: str = ""
    frame_number: int | None = None
    time_epoch: float | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
