from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from traceweaver.core.contracts import AnalysisScope, ScopeDiagnosis


class ProfileDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""


class ProfileCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profiles: list[ProfileDescriptor] = Field(default_factory=list)


class ScopeSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope_id: str
    scope_type: str
    display_name: str = ""
    start_time_epoch: float | None = None
    end_time_epoch: float | None = None
    child_count: int = 0


class ScopeCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    file_name: str
    profile_name: str
    scope_count: int
    warnings: list[str] = Field(default_factory=list)
    scopes: list[ScopeSummary] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    file_name: str
    profile_name: str
    scope_count: int
    overall_verdict: str = "INCONCLUSIVE"
    overall_failure_point: str | None = None
    overall_root_cause: str | None = None
    overall_confidence: str = "low"
    warnings: list[str] = Field(default_factory=list)
    scopes: list[AnalysisScope] = Field(default_factory=list)
    diagnoses: list[ScopeDiagnosis] = Field(default_factory=list)
