from pydantic import BaseModel, ConfigDict, Field

from traceweaver.models.events import DetectedEvent
from traceweaver.models.pdu import PDUSessionFlow
from traceweaver.models.records import NormalizedRecord
from traceweaver.models.sbi import SBICall


class UESession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    ran_ue_ngap_id: str | None = None
    amf_ue_ngap_id: str | None = None
    suci: str | None = None
    supi: str | None = None
    start_time_epoch: float | None = None
    end_time_epoch: float | None = None
    source_record_count: int = 0
    event_count: int = 0
    sbi_call_count: int = 0
    pdu_session_count: int = 0
    frame_numbers: list[int] = Field(default_factory=list)
    records: list[NormalizedRecord] = Field(default_factory=list)
    events: list[DetectedEvent] = Field(default_factory=list)
    sbi_calls: list[SBICall] = Field(default_factory=list)
    pdu_sessions: list[PDUSessionFlow] = Field(default_factory=list)


class UESessionSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    file_name: str
    session_count: int
    warnings: list[str] = Field(default_factory=list)
    sessions: list[UESession] = Field(default_factory=list)
