from pydantic import BaseModel, ConfigDict, Field


class SBICall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection_key: str
    tcp_stream: int | None = None
    stream_id: int
    service: str
    method: str | None = None
    path: str | None = None
    status: int | None = None
    request_frame: int | None = None
    response_frame: int | None = None
    request_time_epoch: float | None = None
    response_time_epoch: float | None = None
    src_ip: str | None = None
    dst_ip: str | None = None
    identity: str | None = None
    matched_session_id: str | None = None
    match_confidence: str | None = None
    match_reason: str | None = None


class SBICallSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    file_name: str
    call_count: int
    warnings: list[str] = Field(default_factory=list)
    calls: list[SBICall] = Field(default_factory=list)
