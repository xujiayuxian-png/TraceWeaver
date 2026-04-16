from __future__ import annotations

from typing import Protocol

from traceweaver.core.agent.tools import InvestigationToolRegistry
from traceweaver.core.analysis.options import AnalysisOptions
from traceweaver.core.analysis.result import AnalysisResult
from traceweaver.core.contracts import DiagnosisContext, ScopeDiagnosis


class AnalysisProfile(Protocol):
    name: str
    description: str

    def analyze_capture(
        self,
        path: str,
        *,
        options: AnalysisOptions,
        llm_provider=None,
    ) -> AnalysisResult: ...

    def build_diagnosis_contexts(
        self,
        path: str,
        *,
        options: AnalysisOptions,
        llm_provider=None,
    ) -> tuple[AnalysisResult, list[DiagnosisContext]]: ...

    def build_investigation_tool_registry(
        self,
        context: DiagnosisContext,
        diagnosis: ScopeDiagnosis | None,
    ) -> InvestigationToolRegistry: ...
