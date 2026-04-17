from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from traceweaver.core.contracts.evidence import EvidenceItem
from traceweaver.core.contracts.scope import AnalysisScope
from traceweaver.core.contracts.signal import DiagnosticSignal
from traceweaver.core.contracts.visibility import VisibilityAssessment


class DiagnosisContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_name: str
    scope: AnalysisScope
    signals: list[DiagnosticSignal] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    visibility: VisibilityAssessment | None = None
    knowledge_refs: list[str] = Field(default_factory=list)


class ScopeDiagnosis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope_id: str
    scope_type: str
    verdict: str
    failure_point: str | None = None
    root_cause: str | None = None
    confidence: str = "low"
    summary: str = ""
    signal_names: list[str] = Field(default_factory=list)
    sbi_paths: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    investigation_trace: list[dict] = Field(default_factory=list)
