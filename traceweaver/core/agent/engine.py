from __future__ import annotations

from pathlib import Path

from traceweaver.core.agent.result import InvestigationResult, InvestigationStep, ScopeInvestigation
from traceweaver.core.analysis.options import AnalysisOptions
from traceweaver.core.contracts import DiagnosisContext, ScopeDiagnosis
from traceweaver.core.profile import get_profile


def investigate_capture(
    path: str | Path,
    *,
    profile: str = "open5gs_5gc",
    llm_provider=None,
    options: AnalysisOptions | None = None,
) -> InvestigationResult:
    resolved_options = options or AnalysisOptions()
    profile_impl = get_profile(profile)
    analysis_result, contexts = profile_impl.build_diagnosis_contexts(
        str(path),
        options=resolved_options,
        llm_provider=llm_provider,
    )

    diagnosis_index = {item.scope_id: item for item in analysis_result.diagnoses}
    investigations = [
        _investigate_scope(context, diagnosis_index.get(context.scope.scope_id))
        for context in contexts
    ]

    warnings = list(analysis_result.warnings)
    warnings.append(f"investigation_engine: generic ({len(contexts)} contexts)")

    return InvestigationResult(
        path=analysis_result.path,
        file_name=analysis_result.file_name,
        profile_name=analysis_result.profile_name,
        scope_count=analysis_result.scope_count,
        overall_verdict=analysis_result.overall_verdict,
        overall_failure_point=analysis_result.overall_failure_point,
        overall_root_cause=analysis_result.overall_root_cause,
        overall_confidence=analysis_result.overall_confidence,
        warnings=warnings,
        diagnoses=list(analysis_result.diagnoses),
        contexts=contexts,
        investigations=investigations,
    )


def _investigate_scope(
    context: DiagnosisContext,
    diagnosis: ScopeDiagnosis | None,
) -> ScopeInvestigation:
    steps: list[InvestigationStep] = []
    evidence_refs = [item.evidence_id for item in context.evidence]
    hypotheses = _build_hypotheses(context, diagnosis)
    next_actions = _build_next_actions(context, diagnosis)
    visibility = context.visibility

    if visibility is not None:
        steps.append(
            InvestigationStep(
                step_id=f"{context.scope.scope_id}:visibility",
                scope_id=context.scope.scope_id,
                action="assess_visibility",
                summary=f"visibility={visibility.completeness}",
                details={
                    "missing_segments": list(visibility.missing_segments),
                    "weak_links": list(visibility.weak_links),
                    "warnings": list(visibility.warnings),
                },
            )
        )

    if diagnosis is not None:
        steps.append(
            InvestigationStep(
                step_id=f"{context.scope.scope_id}:hypothesis",
                scope_id=context.scope.scope_id,
                action="evaluate_primary_hypothesis",
                summary=diagnosis.summary or diagnosis.verdict,
                details={
                    "verdict": diagnosis.verdict,
                    "failure_point": diagnosis.failure_point,
                    "root_cause": diagnosis.root_cause,
                    "confidence": diagnosis.confidence,
                },
            )
        )

    steps.append(
        InvestigationStep(
            step_id=f"{context.scope.scope_id}:evidence",
            scope_id=context.scope.scope_id,
            action="review_evidence",
            summary=f"evidence_items={len(context.evidence)} signals={len(context.signals)}",
            details={
                "evidence_refs": evidence_refs,
                "signal_names": [item.name for item in context.signals],
            },
        )
    )

    verdict = diagnosis.verdict if diagnosis is not None else "INCONCLUSIVE"
    confidence = diagnosis.confidence if diagnosis is not None else "low"
    summary = diagnosis.summary if diagnosis is not None else f"{context.scope.scope_id} unresolved"

    return ScopeInvestigation(
        scope_id=context.scope.scope_id,
        scope_type=context.scope.scope_type,
        verdict=verdict,
        confidence=confidence,
        summary=summary,
        hypotheses=hypotheses,
        evidence_refs=evidence_refs,
        next_actions=next_actions,
        steps=steps,
    )


def _build_hypotheses(
    context: DiagnosisContext,
    diagnosis: ScopeDiagnosis | None,
) -> list[str]:
    if diagnosis is None:
        return ["scope_diagnosis_missing"]
    if diagnosis.verdict == "FAIL":
        if diagnosis.root_cause:
            return [diagnosis.root_cause]
        if diagnosis.failure_point:
            return [f"failure_at_{diagnosis.failure_point.lower()}"]
        return ["unclassified_failure"]
    if diagnosis.verdict == "INCONCLUSIVE":
        if context.visibility and context.visibility.completeness != "complete":
            return ["capture_visibility_gap"]
        return ["insufficient_decisive_evidence"]
    return ["successful_control_plane_sequence"]


def _build_next_actions(
    context: DiagnosisContext,
    diagnosis: ScopeDiagnosis | None,
) -> list[str]:
    actions: list[str] = []
    visibility = context.visibility
    if visibility is not None and visibility.completeness != "complete":
        actions.append("collect a broader capture to cover missing protocol segments")
    if diagnosis is not None and diagnosis.failure_point:
        actions.append(f"inspect evidence around failure point {diagnosis.failure_point}")
    if diagnosis is not None and diagnosis.root_cause:
        actions.append(f"verify root cause hypothesis {diagnosis.root_cause}")
    if not actions:
        actions.append("review scope timeline and key evidence for confirmation")
    return actions
