from __future__ import annotations

from dataclasses import dataclass, field

from traceweaver.profiles.open5gs_5gc.domain.diagnosis import DiagnosticSignal
from traceweaver.profiles.open5gs_5gc.domain.records import ExtractedRecordSet
from traceweaver.profiles.open5gs_5gc.domain.sessions import UESession


@dataclass
class Open5GSAnalysisRuntime:
    record_set: ExtractedRecordSet
    warnings: list[str] = field(default_factory=list)
    sessions: list[UESession] = field(default_factory=list)
    session_index: dict[str, UESession] = field(default_factory=dict)
    signal_cache: dict[str, list[DiagnosticSignal]] = field(default_factory=dict)

    @property
    def path(self) -> str:
        return self.record_set.path

    @property
    def file_name(self) -> str:
        return self.record_set.file_name
