from __future__ import annotations

from pathlib import Path

from traceweaver.core.analysis.options import AnalysisOptions
from traceweaver.core.analysis.result import AnalysisResult, ProfileCatalog, ScopeCatalog, ScopeSummary
from traceweaver.core.profile import get_profile, list_profile_descriptors


def analyze_capture(
    path: str | Path,
    *,
    profile: str = "open5gs_5gc",
    llm_provider=None,
    options: AnalysisOptions | None = None,
) -> AnalysisResult:
    resolved_options = options or AnalysisOptions()
    profile_impl = get_profile(profile)
    return profile_impl.analyze_capture(str(path), options=resolved_options, llm_provider=llm_provider)


def list_profiles() -> ProfileCatalog:
    return ProfileCatalog(profiles=list_profile_descriptors())


def list_scope_summaries(
    path: str | Path,
    *,
    profile: str = "open5gs_5gc",
    llm_provider=None,
    options: AnalysisOptions | None = None,
) -> ScopeCatalog:
    result = analyze_capture(path, profile=profile, llm_provider=llm_provider, options=options)
    return ScopeCatalog(
        path=result.path,
        file_name=result.file_name,
        profile_name=result.profile_name,
        scope_count=result.scope_count,
        warnings=list(result.warnings),
        scopes=[
            ScopeSummary(
                scope_id=scope.scope_id,
                scope_type=scope.scope_type,
                display_name=scope.display_name,
                start_time_epoch=scope.start_time_epoch,
                end_time_epoch=scope.end_time_epoch,
                child_count=len(scope.children),
            )
            for scope in result.scopes
        ],
    )
