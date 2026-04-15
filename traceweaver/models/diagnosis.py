from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class DiagnosticSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    source: str
    frame_number: int | None = None
    time_epoch: float | None = None
    details: dict[str, str | int | float | None] = Field(default_factory=dict)


class SessionDiagnosis(BaseModel):
    """Diagnosis result for a single UE session."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    verdict: str
    failure_point: str | None = None
    root_cause: str | None = None
    confidence: str = "low"
    signals: list[DiagnosticSignal] = Field(default_factory=list)
    signal_names: list[str] = Field(default_factory=list)
    sbi_paths: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class DiagnosisReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    file_name: str
    session_count: int
    overall_verdict: str = "INCONCLUSIVE"
    overall_failure_point: str | None = None
    overall_root_cause: str | None = None
    overall_confidence: str = "low"
    warnings: list[str] = Field(default_factory=list)
    sessions: list[SessionDiagnosis] = Field(default_factory=list)
