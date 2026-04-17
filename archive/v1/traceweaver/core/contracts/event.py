from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StructuredEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    scope_hint: str = ""
    event_type: str
    protocol: str
    time_epoch: float
    frame_number: int
    severity: str = "info"
    key_fields: dict[str, Any] = Field(default_factory=dict)
    attributes: dict[str, Any] = Field(default_factory=dict)
