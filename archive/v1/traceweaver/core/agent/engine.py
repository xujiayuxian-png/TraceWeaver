from __future__ import annotations

from pathlib import Path

from traceweaver.core.agent.planner import InvestigationPlan, build_investigation_plan, evaluate_termination, reconsider_termination_with_llm
from traceweaver.core.agent.result import InvestigationResult, InvestigationStep, ScopeInvestigation
from traceweaver.core.agent.tools import InvestigationToolRegistry, InvestigationToolResult
from traceweaver.core.analysis.engine import build_analysis_artifacts
from traceweaver.core.analysis.options import AnalysisOptions
from traceweaver.core.contracts import DiagnosisContext, ScopeDiagnosis
from traceweaver.core.profile import get_profile

MAX_INVESTIGATION_ROUNDS = 3


def investigate_capture(
    path: str | Path,
    *,
    profile: str = "open5gs_5gc",
    scope_id: str | None = None,
    llm_provider=None,
    options: AnalysisOptions | None = None,
) -> InvestigationResult:
    resolved_options = options or AnalysisOptions()
    profile_impl = get_profile(profile)
    artifacts = build_analysis_artifacts(
        str(path),
        profile=profile,
        llm_provider=llm_provider,
        options=resolved_options,
    )
    analysis_result = artifacts.result
    contexts = artifacts.contexts

    diagnosis_index = {item.scope_id: item for item in analysis_result.diagnoses}
    if scope_id is not None:
        contexts = [item for item in contexts if item.scope.scope_id == scope_id]
        if not contexts:
            raise ValueError(f"scope not found: {scope_id}")

    investigations: list[ScopeInvestigation] = []
    for context in contexts:
        diagnosis = diagnosis_index.get(context.scope.scope_id)
        registry = profile_impl.build_investigation_tool_registry(context, diagnosis)
        investigation = _investigate_scope(
            context,
            diagnosis,
            registry,
            llm_provider=llm_provider,
        )
        investigations.append(investigation)
        if diagnosis is not None:
            diagnosis.investigation_trace = _build_trace_payload(investigation)

    warnings = list(analysis_result.warnings)
    warnings.append(f"investigation_engine: planner+tools+loop ({len(contexts)} contexts)")

    selected_diagnoses = [
        diagnosis_index[item.scope.scope_id]
        for item in contexts
        if item.scope.scope_id in diagnosis_index
    ]

    return InvestigationResult(
        path=analysis_result.path,
        file_name=analysis_result.file_name,
        profile_name=analysis_result.profile_name,
        scope_count=len(contexts),
        overall_verdict=analysis_result.overall_verdict,
        overall_failure_point=analysis_result.overall_failure_point,
        overall_root_cause=analysis_result.overall_root_cause,
        overall_confidence=analysis_result.overall_confidence,
        selected_scope_id=scope_id,
        warnings=warnings,
        diagnoses=selected_diagnoses,
        contexts=contexts,
        investigations=investigations,
    )


def _investigate_scope(
    context: DiagnosisContext,
    diagnosis: ScopeDiagnosis | None,
    registry: InvestigationToolRegistry,
    *,
    llm_provider=None,
) -> ScopeInvestigation:
    steps: list[InvestigationStep] = []
    evidence_refs = [item.evidence_id for item in context.evidence]
    tool_results: list[InvestigationToolResult] = []
    executed_tools: list[str] = []
    hypothesis_statements: list[str] = []
    last_plan: InvestigationPlan | None = None
    termination = None
    round_index = 1
    remaining_tools = registry.list_names()

    while round_index <= MAX_INVESTIGATION_ROUNDS:
        plan = build_investigation_plan(
            context,
            diagnosis,
            remaining_tools,
            llm_provider=llm_provider,
            previous_results=tool_results,
            round_index=round_index,
            max_rounds=MAX_INVESTIGATION_ROUNDS,
        )
        last_plan = plan
        for statement in (item.statement for item in plan.hypotheses):
            if statement not in hypothesis_statements:
                hypothesis_statements.append(statement)

        steps.append(
            InvestigationStep(
                step_id=f"{context.scope.scope_id}:round-{round_index}:plan",
                scope_id=context.scope.scope_id,
                action="build_plan",
                summary=f"planned_tools={len(plan.tool_sequence)} hypotheses={len(plan.hypotheses)}",
                details=plan.model_dump(),
            )
        )

        primary_hypothesis = hypothesis_statements[0] if hypothesis_statements else None
        round_tools = [item for item in plan.tool_sequence if item in remaining_tools]

        for tool_name in round_tools:
            result = registry.execute(
                tool_name,
                context=context,
                diagnosis=diagnosis,
                hypothesis=primary_hypothesis,
            )
            result = result.model_copy(update={"round_index": round_index})
            tool_results.append(result)
            executed_tools.append(tool_name)
            evidence_refs.extend(result.evidence_refs)
            steps.append(
                InvestigationStep(
                    step_id=f"{context.scope.scope_id}:round-{round_index}:tool:{tool_name}",
                    scope_id=context.scope.scope_id,
                    action="run_tool",
                    summary=result.summary,
                    details={
                        "round_index": round_index,
                        "tool_name": tool_name,
                        "hypothesis": primary_hypothesis,
                        "result": result.model_dump(),
                    },
                )
            )

        remaining_tools = [item for item in registry.list_names() if item not in executed_tools]
        rule_termination = evaluate_termination(
            context,
            diagnosis,
            executed_tools=executed_tools,
            remaining_tools=remaining_tools,
            round_index=round_index,
            max_rounds=MAX_INVESTIGATION_ROUNDS,
            tool_results=tool_results,
        )
        termination = rule_termination
        if llm_provider is not None:
            llm_termination = reconsider_termination_with_llm(
                context,
                diagnosis,
                rule_termination=rule_termination,
                remaining_tools=remaining_tools,
                executed_tools=executed_tools,
                tool_results=tool_results,
                llm_provider=llm_provider,
                round_index=round_index,
                max_rounds=MAX_INVESTIGATION_ROUNDS,
            )
            if llm_termination is not None:
                termination = llm_termination

        steps.append(
            InvestigationStep(
                step_id=f"{context.scope.scope_id}:round-{round_index}:termination",
                scope_id=context.scope.scope_id,
                action="terminate_investigation",
                summary=termination.reason,
                details={
                    "round_index": round_index,
                    **termination.model_dump(),
                },
            )
        )

        if termination.status != "continue" or not remaining_tools:
            break
        round_index += 1

    if termination is None:
        termination = evaluate_termination(
            context,
            diagnosis,
            executed_tools=executed_tools,
            remaining_tools=remaining_tools,
            round_index=round_index,
            max_rounds=MAX_INVESTIGATION_ROUNDS,
            tool_results=tool_results,
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
        plan=last_plan,
        hypotheses=hypothesis_statements,
        evidence_refs=_dedupe(evidence_refs),
        executed_tools=executed_tools,
        tool_results=tool_results,
        termination=termination,
        next_actions=list(termination.next_actions),
        round_count=round_index,
        steps=steps,
    )


def _build_trace_payload(investigation: ScopeInvestigation) -> list[dict]:
    payload: list[dict] = []
    for step in investigation.steps:
        if step.action == "build_plan":
            payload.append({"phase": "plan", "data": step.details})
        elif step.action == "run_tool":
            payload.append({"phase": "tool", "data": step.details.get("result", step.details)})
        elif step.action == "terminate_investigation":
            payload.append({"phase": "termination", "data": step.details})
    return payload


def _dedupe(items: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered
