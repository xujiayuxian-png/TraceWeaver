from pydantic import BaseModel, ConfigDict, Field

from traceweaver.models.events import DetectedEvent
from traceweaver.models.sbi import SBICall


class PFCPFlow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frame_number: int
    time_epoch: float
    msg_type: int | None = None
    seid: str | None = None
    f_seid_ipv4: str | None = None
    cause: int | None = None
    src_ip: str | None = None
    dst_ip: str | None = None
    matched_by: str | None = None


class PDUSessionFlow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pdu_session_id: str
    parent_session_id: str | None = None
    start_time_epoch: float | None = None
    end_time_epoch: float | None = None
    event_count: int = 0
    sbi_call_count: int = 0
    pfcp_flow_count: int = 0
    smf_ips: list[str] = Field(default_factory=list)
    events: list[DetectedEvent] = Field(default_factory=list)
    sbi_calls: list[SBICall] = Field(default_factory=list)
    pfcp_flows: list[PFCPFlow] = Field(default_factory=list)


class PDUSessionSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    file_name: str
    pdu_session_count: int
    warnings: list[str] = Field(default_factory=list)
    pdu_sessions: list[PDUSessionFlow] = Field(default_factory=list)
