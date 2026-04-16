from __future__ import annotations

from pathlib import Path

from traceweaver.core.agent.planner import InvestigationPlan, build_investigation_plan, evaluate_termination
from traceweaver.core.agent.result import InvestigationResult, InvestigationStep, ScopeInvestigation
from traceweaver.core.agent.tools import InvestigationToolRegistry, InvestigationToolResult
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
    investigations: list[ScopeInvestigation] = []
    for context in contexts:
        diagnosis = diagnosis_index.get(context.scope.scope_id)
        registry = profile_impl.build_investigation_tool_registry(context, diagnosis)
        plan = build_investigation_plan(context, diagnosis, registry.list_names())
        investigation = _investigate_scope(context, diagnosis, registry, plan)
        investigations.append(investigation)
        if diagnosis is not None:
            diagnosis.investigation_trace = _build_trace_payload(investigation)

    warnings = list(analysis_result.warnings)
    warnings.append(f"investigation_engine: planner+tools ({len(contexts)} contexts)")

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
    registry: InvestigationToolRegistry,
    plan: InvestigationPlan,
) -> ScopeInvestigation:
    steps: list[InvestigationStep] = [
        InvestigationStep(
            step_id=f"{context.scope.scope_id}:plan",
            scope_id=context.scope.scope_id,
            action="build_plan",
            summary=f"planned_tools={len(plan.tool_sequence)} hypotheses={len(plan.hypotheses)}",
            details=plan.model_dump(),
        )
    ]
    evidence_refs = [item.evidence_id for item in context.evidence]
    tool_results: list[InvestigationToolResult] = []
    executed_tools: list[str] = []
    hypotheses = [item.statement for item in plan.hypotheses]
    primary_hypothesis = hypotheses[0] if hypotheses else None

    for tool_name in plan.tool_sequence:
        result = registry.execute(
            tool_name,
            context=context,
            diagnosis=diagnosis,
            hypothesis=primary_hypothesis,
        )
        tool_results.append(result)
        executed_tools.append(tool_name)
        evidence_refs.extend(result.evidence_refs)
        steps.append(
            InvestigationStep(
                step_id=f"{context.scope.scope_id}:tool:{tool_name}",
                scope_id=context.scope.scope_id,
                action="run_tool",
                summary=result.summary,
                details={
                    "tool_name": tool_name,
                    "hypothesis": primary_hypothesis,
                    "result": result.model_dump(),
                },
            )
        )

    termination = evaluate_termination(
        context,
        diagnosis,
        executed_tools=executed_tools,
    )
    steps.append(
        InvestigationStep(
            step_id=f"{context.scope.scope_id}:termination",
            scope_id=context.scope.scope_id,
            action="terminate_investigation",
            summary=termination.reason,
            details=termination.model_dump(),
        )
    )

    verdict = diagnosis.verdict if diagnosis is not None else "INCONCLUSIVE"
    confidence = diagnosis.confidence if diagnosis is not None else termination.confidence
    summary = diagnosis.summary if diagnosis is not None else termination.reason

    return ScopeInvestigation(
        scope_id=context.scope.scope_id,
        scope_type=context.scope.scope_type,
        verdict=verdict,
        confidence=confidence,
        summary=summary,
        plan=plan,
        hypotheses=hypotheses,
        evidence_refs=_dedupe(evidence_refs),
        executed_tools=executed_tools,
        tool_results=tool_results,
        termination=termination,
        next_actions=list(termination.next_actions),
        steps=steps,
    )


def _build_trace_payload(investigation: ScopeInvestigation) -> list[dict]:
    payload: list[dict] = []
    if investigation.plan is not None:
        payload.append({"phase": "plan", "data": investigation.plan.model_dump()})
    for result in investigation.tool_results:
        payload.append({"phase": "tool", "data": result.model_dump()})
    if investigation.termination is not None:
        payload.append({"phase": "termination", "data": investigation.termination.model_dump()})
    return payload


def _dedupe(items: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered
