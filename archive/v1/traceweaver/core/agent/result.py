from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from traceweaver.core.agent.planner import InvestigationPlan, InvestigationTermination
from traceweaver.core.agent.tools import InvestigationToolResult
from traceweaver.core.contracts import DiagnosisContext, ScopeDiagnosis


class InvestigationStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str
    scope_id: str
    action: str
    status: str = "completed"
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)


class ScopeInvestigation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope_id: str
    scope_type: str
    verdict: str
    confidence: str = "low"
    summary: str = ""
    plan: InvestigationPlan | None = None
    hypotheses: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    executed_tools: list[str] = Field(default_factory=list)
    tool_results: list[InvestigationToolResult] = Field(default_factory=list)
    termination: InvestigationTermination | None = None
    next_actions: list[str] = Field(default_factory=list)
    round_count: int = 1
    steps: list[InvestigationStep] = Field(default_factory=list)


class InvestigationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    file_name: str
    profile_name: str
    scope_count: int
    overall_verdict: str = "INCONCLUSIVE"
    overall_failure_point: str | None = None
    overall_root_cause: str | None = None
    overall_confidence: str = "low"
    selected_scope_id: str | None = None
    warnings: list[str] = Field(default_factory=list)
    diagnoses: list[ScopeDiagnosis] = Field(default_factory=list)
    contexts: list[DiagnosisContext] = Field(default_factory=list)
    investigations: list[ScopeInvestigation] = Field(default_factory=list)
