from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field

from traceweaver.core.contracts import DiagnosisContext, ScopeDiagnosis


class InvestigationToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class CallableInvestigationTool:
    name: str
    description: str
    handler: Callable[[DiagnosisContext, ScopeDiagnosis | None, str | None], InvestigationToolResult]

    def run(
        self,
        context: DiagnosisContext,
        diagnosis: ScopeDiagnosis | None,
        *,
        hypothesis: str | None,
    ) -> InvestigationToolResult:
        return self.handler(context, diagnosis, hypothesis)


class InvestigationToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, CallableInvestigationTool] = {}

    def register(self, tool: CallableInvestigationTool) -> None:
        self._tools[tool.name] = tool

    def extend(self, tools: list[CallableInvestigationTool]) -> None:
        for tool in tools:
            self.register(tool)

    def list_names(self) -> list[str]:
        return sorted(self._tools)

    def execute(
        self,
        tool_name: str,
        *,
        context: DiagnosisContext,
        diagnosis: ScopeDiagnosis | None,
        hypothesis: str | None,
    ) -> InvestigationToolResult:
        tool = self._tools[tool_name]
        return tool.run(context, diagnosis, hypothesis=hypothesis)


def build_default_tool_registry() -> InvestigationToolRegistry:
    registry = InvestigationToolRegistry()
    registry.extend(
        [
            CallableInvestigationTool(
                name="knowledge_refs",
                description="List knowledge references attached to the diagnosis context",
                handler=_knowledge_refs_tool,
            ),
            CallableInvestigationTool(
                name="evidence_index",
                description="List evidence identifiers available for the current scope",
                handler=_evidence_index_tool,
            ),
        ]
    )
    return registry


def _knowledge_refs_tool(
    context: DiagnosisContext,
    diagnosis: ScopeDiagnosis | None,
    hypothesis: str | None,
) -> InvestigationToolResult:
    return InvestigationToolResult(
        tool_name="knowledge_refs",
        summary=f"knowledge_refs={len(context.knowledge_refs)}",
        details={
            "knowledge_refs": list(context.knowledge_refs),
            "hypothesis": hypothesis,
            "diagnosis_verdict": diagnosis.verdict if diagnosis is not None else None,
        },
    )


def _evidence_index_tool(
    context: DiagnosisContext,
    diagnosis: ScopeDiagnosis | None,
    hypothesis: str | None,
) -> InvestigationToolResult:
    evidence_refs = [item.evidence_id for item in context.evidence]
    return InvestigationToolResult(
        tool_name="evidence_index",
        summary=f"evidence_items={len(evidence_refs)}",
        details={
            "evidence_refs": evidence_refs,
            "hypothesis": hypothesis,
        },
        evidence_refs=evidence_refs,
    )
