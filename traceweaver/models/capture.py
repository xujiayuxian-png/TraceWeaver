from pydantic import BaseModel, ConfigDict, Field


class ProtocolPresence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ngap: bool
    nas_5gs: bool
    http2: bool
    http2_forced_on_7777: bool
    pfcp: bool


class ToolingInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tshark_version: str
    capinfos_version: str
    tshark_minimum_recommended: str
    tshark_meets_minimum_recommended: bool


class CaptureInspection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    file_name: str
    file_size_bytes: int
    packet_count: int
    duration_seconds: float
    start_time_epoch: float
    end_time_epoch: float
    protocols: ProtocolPresence
    recommended_decode_as: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    tooling: ToolingInfo
