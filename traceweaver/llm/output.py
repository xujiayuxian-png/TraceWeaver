from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


VALID_VERDICTS = {"OK", "FAIL", "FAIL_THEN_OK", "INCONCLUSIVE"}
VALID_CONFIDENCES = {"high", "medium", "low"}


class LLMEvidence(BaseModel):
    model_config = ConfigDict(extra="allow")

    frame_number: int | None = None
    description: str = ""


class LLMDiagnosisOutput(BaseModel):
    """Validated schema for LLM diagnosis JSON output."""

    model_config = ConfigDict(extra="allow")

    verdict: str
    failure_point: str | None = None
    root_cause: str | None = None
    confidence: str = "medium"
    evidence: list[LLMEvidence] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    reasoning: str = ""

    @field_validator("verdict")
    @classmethod
    def validate_verdict(cls, v: str) -> str:
        upper = v.strip().upper()
        if upper not in VALID_VERDICTS:
            raise ValueError(f"verdict must be one of {VALID_VERDICTS}, got '{v}'")
        return upper

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v: str) -> str:
        lower = v.strip().lower()
        if lower not in VALID_CONFIDENCES:
            raise ValueError(f"confidence must be one of {VALID_CONFIDENCES}, got '{v}'")
        return lower


def parse_llm_diagnosis(data: dict) -> LLMDiagnosisOutput:
    return LLMDiagnosisOutput.model_validate(data)
