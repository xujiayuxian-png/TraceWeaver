from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CaptureRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frame_number: int
    time_epoch: float
    time_relative: float | None = None
    primary_protocol: str = ""
    protocol_layers: list[str] = Field(default_factory=list)
    src_ip: str = ""
    dst_ip: str = ""
    src_port: int | None = None
    dst_port: int | None = None
    connection_key: str = ""
    raw_info: str = ""
    fields: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
