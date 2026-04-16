from __future__ import annotations

from typing import Protocol

from traceweaver.core.analysis.options import AnalysisOptions
from traceweaver.core.analysis.result import AnalysisResult


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
