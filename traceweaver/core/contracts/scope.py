from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from traceweaver.core.contracts.event import StructuredEvent
from traceweaver.core.contracts.record import CaptureRecord


class AnalysisScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope_id: str
    scope_type: str
    display_name: str = ""
    start_time_epoch: float | None = None
    end_time_epoch: float | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    records: list[CaptureRecord] = Field(default_factory=list)
    events: list[StructuredEvent] = Field(default_factory=list)
    children: list["AnalysisScope"] = Field(default_factory=list)
    related_entities: dict[str, list[str]] = Field(default_factory=dict)


AnalysisScope.model_rebuild()
