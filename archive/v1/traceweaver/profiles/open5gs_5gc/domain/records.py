from pydantic import BaseModel, ConfigDict, Field


class NormalizedRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frame_number: int
    time_epoch: float
    time_relative: float | None = None
    protocols: list[str] = Field(default_factory=list)
    primary_protocol: str | None = None
    src_ip: str | None = None
    dst_ip: str | None = None
    src_port: int | None = None
    dst_port: int | None = None
    transport_protocol: str | None = None
    fields: dict[str, str] = Field(default_factory=dict)


class ExtractedRecordSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    file_name: str
    display_filter: str
    decode_as: list[str] = Field(default_factory=list)
    tshark_version: str
    resolved_fields: dict[str, str] = Field(default_factory=dict)
    unresolved_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    record_count: int
    records: list[NormalizedRecord] = Field(default_factory=list)
