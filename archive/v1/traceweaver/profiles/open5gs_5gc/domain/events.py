from pydantic import BaseModel, ConfigDict, Field


class DetectedEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frame_number: int
    time_epoch: float
    protocol: str
    event_name: str
    message_type: int | None = None
    cause: int | None = None
    ran_ue_ngap_id: str | None = None
    amf_ue_ngap_id: str | None = None
    pdu_session_id: str | None = None
    src_ip: str | None = None
    dst_ip: str | None = None
    fields: dict[str, str] = Field(default_factory=dict)


class DetectedEventSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    file_name: str
    event_count: int
    warnings: list[str] = Field(default_factory=list)
    events: list[DetectedEvent] = Field(default_factory=list)
