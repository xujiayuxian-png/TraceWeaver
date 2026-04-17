from __future__ import annotations

from typing import Any, Protocol

from traceweaver.core.agent.tools import InvestigationToolRegistry
from traceweaver.core.analysis.options import AnalysisOptions
from traceweaver.core.contracts import AnalysisScope, DiagnosisContext, DiagnosticSignal, EvidenceItem, ScopeDiagnosis, VisibilityAssessment


class AnalysisProfile(Protocol):
    name: str
    description: str

    def extract(
        self,
        path: str,
        *,
        options: AnalysisOptions,
    ) -> Any: ...

    def build_scopes(
        self,
        runtime: Any,
        *,
        options: AnalysisOptions,
    ) -> list[AnalysisScope]: ...

    def annotate_signals(
        self,
        scope: AnalysisScope,
        runtime: Any,
        *,
        options: AnalysisOptions,
    ) -> list[DiagnosticSignal]: ...

    def assess_visibility(
        self,
        scope: AnalysisScope,
        runtime: Any,
        signals: list[DiagnosticSignal],
        *,
        options: AnalysisOptions,
    ) -> VisibilityAssessment | None: ...

    def collect_evidence(
        self,
        scope: AnalysisScope,
        runtime: Any,
        signals: list[DiagnosticSignal],
        visibility: VisibilityAssessment | None,
        *,
        options: AnalysisOptions,
    ) -> list[EvidenceItem]: ...

    def diagnose_scope(
        self,
        scope: AnalysisScope,
        runtime: Any,
        signals: list[DiagnosticSignal],
        visibility: VisibilityAssessment | None,
        *,
        llm_provider=None,
        options: AnalysisOptions,
    ) -> ScopeDiagnosis: ...

    def build_investigation_tool_registry(
        self,
        context: DiagnosisContext,
        diagnosis: ScopeDiagnosis | None,
    ) -> InvestigationToolRegistry: ...
