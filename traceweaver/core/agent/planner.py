from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from traceweaver.core.contracts import DiagnosisContext, ScopeDiagnosis


class InvestigationHypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hypothesis_id: str
    statement: str
    priority: str = "medium"
    rationale: str = ""
    tool_names: list[str] = Field(default_factory=list)


class InvestigationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope_id: str
    hypotheses: list[InvestigationHypothesis] = Field(default_factory=list)
    tool_sequence: list[str] = Field(default_factory=list)
    stop_when: str = "primary_hypothesis_sufficiently_supported"


class InvestigationTermination(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = "completed"
    reason: str
    confidence: str = "low"
    next_actions: list[str] = Field(default_factory=list)


def build_investigation_plan(
    context: DiagnosisContext,
    diagnosis: ScopeDiagnosis | None,
    available_tools: list[str],
) -> InvestigationPlan:
    hypotheses = _build_hypotheses(context, diagnosis, available_tools)
    tool_sequence = _build_tool_sequence(hypotheses, available_tools)
    return InvestigationPlan(
        scope_id=context.scope.scope_id,
        hypotheses=hypotheses,
        tool_sequence=tool_sequence,
        stop_when=_stop_condition(context, diagnosis),
    )


def evaluate_termination(
    context: DiagnosisContext,
    diagnosis: ScopeDiagnosis | None,
    *,
    executed_tools: list[str],
) -> InvestigationTermination:
    visibility = context.visibility
    next_actions: list[str] = []

    if visibility is not None and visibility.completeness == "partial":
        next_actions.append("collect a broader capture that includes missing protocol segments")
        return InvestigationTermination(
            reason="visibility_gap_detected",
            confidence="medium",
            next_actions=_merge_actions(next_actions, diagnosis),
        )

    if diagnosis is None:
        next_actions.append("produce a baseline diagnosis before further investigation")
        return InvestigationTermination(
            reason="diagnosis_missing",
            confidence="low",
            next_actions=next_actions,
        )

    if diagnosis.verdict == "FAIL":
        next_actions.append("validate failure evidence against upstream and downstream frames")
        return InvestigationTermination(
            reason="failure_hypothesis_supported",
            confidence=diagnosis.confidence,
            next_actions=_merge_actions(next_actions, diagnosis),
        )

    if diagnosis.verdict == "INCONCLUSIVE":
        next_actions.append("gather more decisive protocol evidence for the inconclusive scope")
        return InvestigationTermination(
            reason="insufficient_decisive_evidence",
            confidence=diagnosis.confidence,
            next_actions=_merge_actions(next_actions, diagnosis),
        )

    next_actions.append("confirm success path with key control-plane evidence")
    return InvestigationTermination(
        reason=f"investigation_complete_after_{len(executed_tools)}_tool_calls",
        confidence=diagnosis.confidence,
        next_actions=_merge_actions(next_actions, diagnosis),
    )


def _build_hypotheses(
    context: DiagnosisContext,
    diagnosis: ScopeDiagnosis | None,
    available_tools: list[str],
) -> list[InvestigationHypothesis]:
    if diagnosis is None:
        return [
            InvestigationHypothesis(
                hypothesis_id=f"{context.scope.scope_id}:missing-diagnosis",
                statement="scope_diagnosis_missing",
                priority="high",
                rationale="investigation cannot proceed deeply without a scope diagnosis",
                tool_names=_preferred_tools(available_tools, "scope_overview", "signal_focus", "knowledge_refs"),
            )
        ]

    if diagnosis.verdict == "FAIL":
        statement = diagnosis.root_cause or diagnosis.failure_point or "unclassified_failure"
        return [
            InvestigationHypothesis(
                hypothesis_id=f"{context.scope.scope_id}:primary-failure",
                statement=statement,
                priority="high",
                rationale=diagnosis.summary or diagnosis.verdict,
                tool_names=_preferred_tools(available_tools, "scope_overview", "signal_focus", "evidence_focus", "visibility_analysis"),
            )
        ]

    if diagnosis.verdict == "INCONCLUSIVE":
        statement = "capture_visibility_gap" if context.visibility and context.visibility.completeness != "complete" else "insufficient_decisive_evidence"
        return [
            InvestigationHypothesis(
                hypothesis_id=f"{context.scope.scope_id}:inconclusive",
                statement=statement,
                priority="high",
                rationale="diagnosis is inconclusive and needs corroborating evidence",
                tool_names=_preferred_tools(available_tools, "visibility_analysis", "evidence_focus", "signal_focus", "knowledge_refs"),
            )
        ]

    return [
        InvestigationHypothesis(
            hypothesis_id=f"{context.scope.scope_id}:success-path",
            statement="successful_control_plane_sequence",
            priority="medium",
            rationale=diagnosis.summary or "scope appears healthy",
            tool_names=_preferred_tools(available_tools, "scope_overview", "signal_focus", "evidence_focus"),
        )
    ]


def _build_tool_sequence(
    hypotheses: list[InvestigationHypothesis],
    available_tools: list[str],
) -> list[str]:
    sequence: list[str] = []
    for hypothesis in hypotheses:
        for tool_name in hypothesis.tool_names:
            if tool_name in available_tools and tool_name not in sequence:
                sequence.append(tool_name)
    for fallback in ["scope_overview", "evidence_focus", "knowledge_refs"]:
        if fallback in available_tools and fallback not in sequence:
            sequence.append(fallback)
    return sequence


def _stop_condition(context: DiagnosisContext, diagnosis: ScopeDiagnosis | None) -> str:
    if diagnosis is None:
        return "stop_after_baseline_scope_review"
    if diagnosis.verdict == "FAIL":
        return "stop_when_failure_hypothesis_has_supporting_evidence"
    if diagnosis.verdict == "INCONCLUSIVE":
        if context.visibility and context.visibility.completeness != "complete":
            return "stop_when_visibility_gap_is_confirmed"
        return "stop_when_inconclusive_state_is_explained"
    return "stop_when_success_path_is_confirmed"


def _preferred_tools(available_tools: list[str], *preferred: str) -> list[str]:
    return [item for item in preferred if item in available_tools]


def _merge_actions(base: list[str], diagnosis: ScopeDiagnosis | None) -> list[str]:
    actions = list(base)
    if diagnosis is not None and diagnosis.failure_point:
        actions.append(f"inspect evidence around failure point {diagnosis.failure_point}")
    if diagnosis is not None and diagnosis.root_cause:
        actions.append(f"verify root cause hypothesis {diagnosis.root_cause}")
    if not actions:
        actions.append("review scope timeline and key evidence for confirmation")
    return actions
