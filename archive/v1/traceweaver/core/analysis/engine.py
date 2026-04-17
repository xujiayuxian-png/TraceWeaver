from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from traceweaver.core.analysis.options import AnalysisOptions
from traceweaver.core.analysis.result import AnalysisResult, ProfileCatalog, ScopeCatalog, ScopeSummary
from traceweaver.core.contracts import DiagnosisContext, ScopeDiagnosis
from traceweaver.core.profile import get_profile, list_profile_descriptors


@dataclass
class AnalysisArtifacts:
    result: AnalysisResult
    contexts: list[DiagnosisContext]


def analyze_capture(
    path: str | Path,
    *,
    profile: str = "open5gs_5gc",
    llm_provider=None,
    options: AnalysisOptions | None = None,
) -> AnalysisResult:
    return build_analysis_artifacts(
        path,
        profile=profile,
        llm_provider=llm_provider,
        options=options,
    ).result


def build_analysis_artifacts(
    path: str | Path,
    *,
    profile: str = "open5gs_5gc",
    llm_provider=None,
    options: AnalysisOptions | None = None,
) -> AnalysisArtifacts:
    resolved_options = options or AnalysisOptions()
    profile_impl = get_profile(profile)
    runtime = profile_impl.extract(str(path), options=resolved_options)
    scopes = profile_impl.build_scopes(runtime, options=resolved_options)

    diagnoses: list[ScopeDiagnosis] = []
    contexts: list[DiagnosisContext] = []
    knowledge_refs = list(getattr(profile_impl, "knowledge_refs", []))

    for scope in scopes:
        signals = profile_impl.annotate_signals(scope, runtime, options=resolved_options)
        visibility = profile_impl.assess_visibility(scope, runtime, signals, options=resolved_options)
        evidence = profile_impl.collect_evidence(
            scope,
            runtime,
            signals,
            visibility,
            options=resolved_options,
        )
        diagnosis = profile_impl.diagnose_scope(
            scope,
            runtime,
            signals,
            visibility,
            llm_provider=llm_provider,
            options=resolved_options,
        )
        diagnoses.append(diagnosis)
        contexts.append(
            DiagnosisContext(
                profile_name=profile_impl.name,
                scope=scope,
                signals=signals,
                evidence=evidence,
                visibility=visibility,
                knowledge_refs=knowledge_refs,
            )
        )

    overall = _compute_overall_verdict(diagnoses)
    result = AnalysisResult(
        path=runtime.path,
        file_name=runtime.file_name,
        profile_name=profile_impl.name,
        scope_count=len(scopes),
        overall_verdict=overall[0],
        overall_failure_point=overall[1],
        overall_root_cause=overall[2],
        overall_confidence=overall[3],
        warnings=list(getattr(runtime, "warnings", [])),
        scopes=scopes,
        diagnoses=diagnoses,
    )
    return AnalysisArtifacts(result=result, contexts=contexts)


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


def _compute_overall_verdict(
    diagnoses: list[ScopeDiagnosis],
) -> tuple[str, str | None, str | None, str]:
    if not diagnoses:
        return ("INCONCLUSIVE", None, None, "low")

    if len(diagnoses) == 1:
        d = diagnoses[0]
        return (d.verdict, d.failure_point, d.root_cause, d.confidence)

    verdicts = {d.verdict for d in diagnoses}

    if verdicts == {"FAIL", "OK"} or verdicts == {"FAIL", "OK", "INCONCLUSIVE"}:
        fail_diag = next(d for d in diagnoses if d.verdict == "FAIL")
        return (
            "FAIL_THEN_OK",
            fail_diag.failure_point,
            fail_diag.root_cause,
            "high",
        )

    if verdicts == {"OK"}:
        return ("OK", None, None, "high")

    if "FAIL" in verdicts:
        fail_diag = next(d for d in diagnoses if d.verdict == "FAIL")
        return ("FAIL", fail_diag.failure_point, fail_diag.root_cause, fail_diag.confidence)

    if verdicts == {"INCONCLUSIVE"}:
        return ("INCONCLUSIVE", None, None, "low")

    primary = diagnoses[0]
    return (primary.verdict, primary.failure_point, primary.root_cause, primary.confidence)
