from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from traceweaver.core.agent.prompts import build_investigation_planner_prompt, build_investigation_termination_prompt
from traceweaver.core.agent.tools import InvestigationToolResult
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
    round_index: int = 1
    planning_source: str = "rule"
    selected_hypothesis_id: str | None = None
    hypotheses: list[InvestigationHypothesis] = Field(default_factory=list)
    tool_sequence: list[str] = Field(default_factory=list)
    stop_when: str = "primary_hypothesis_sufficiently_supported"


class InvestigationTermination(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = "completed"
    reason: str
    confidence: str = "low"
    source: str = "rule"
    reasoning: str = ""
    next_actions: list[str] = Field(default_factory=list)


def build_investigation_plan(
    context: DiagnosisContext,
    diagnosis: ScopeDiagnosis | None,
    available_tools: list[str],
    *,
    llm_provider=None,
    previous_results: list[InvestigationToolResult] | None = None,
    round_index: int = 1,
    max_rounds: int = 3,
) -> InvestigationPlan:
    hypotheses = _build_hypotheses(context, diagnosis, available_tools)
    previous = previous_results or []
    planning_source = "rule"
    selected_hypothesis_id = hypotheses[0].hypothesis_id if hypotheses else None
    tool_sequence = _build_tool_sequence(
        hypotheses,
        available_tools,
        diagnosis=diagnosis,
        round_index=round_index,
        max_rounds=max_rounds,
    )

    if llm_provider is not None and hypotheses and available_tools:
        llm_ranked = _rank_with_llm(
            context,
            diagnosis,
            hypotheses,
            available_tools,
            previous,
            llm_provider=llm_provider,
            round_index=round_index,
            max_rounds=max_rounds,
        )
        if llm_ranked is not None:
            hypotheses = llm_ranked["hypotheses"]
            tool_sequence = llm_ranked["tool_sequence"]
            planning_source = "llm"
            selected_hypothesis_id = hypotheses[0].hypothesis_id if hypotheses else selected_hypothesis_id

    return InvestigationPlan(
        scope_id=context.scope.scope_id,
        round_index=round_index,
        planning_source=planning_source,
        selected_hypothesis_id=selected_hypothesis_id,
        hypotheses=hypotheses,
        tool_sequence=tool_sequence,
        stop_when=_stop_condition(context, diagnosis),
    )


def evaluate_termination(
    context: DiagnosisContext,
    diagnosis: ScopeDiagnosis | None,
    *,
    executed_tools: list[str],
    remaining_tools: list[str],
    round_index: int,
    max_rounds: int,
    tool_results: list[InvestigationToolResult],
) -> InvestigationTermination:
    visibility = context.visibility
    next_actions: list[str] = []

    if round_index < max_rounds and remaining_tools:
        if diagnosis is None:
            return InvestigationTermination(
                status="continue",
                reason="need_additional_scope_review",
                confidence="low",
                next_actions=["continue investigation with additional tools"],
            )
        if diagnosis.verdict == "FAIL":
            if any(tool in remaining_tools for tool in ["protocol_drilldown", "frame_targeting"]):
                return InvestigationTermination(
                    status="continue",
                    reason="continue_for_failure_drilldown",
                    confidence=diagnosis.confidence,
                    next_actions=["run drilldown tools to validate failure frames"],
                )
        if diagnosis.verdict == "INCONCLUSIVE":
            return InvestigationTermination(
                status="continue",
                reason="continue_for_additional_evidence",
                confidence=diagnosis.confidence,
                next_actions=["continue with more targeted evidence gathering tools"],
            )
        if diagnosis.verdict == "OK" and round_index == 1 and any(tool in remaining_tools for tool in ["protocol_drilldown", "frame_targeting"]):
            return InvestigationTermination(
                status="continue",
                reason="continue_for_success_confirmation",
                confidence=diagnosis.confidence,
                next_actions=["confirm success path with protocol drilldown or frame targeting"],
            )

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


def reconsider_termination_with_llm(
    context: DiagnosisContext,
    diagnosis: ScopeDiagnosis | None,
    *,
    rule_termination: InvestigationTermination,
    remaining_tools: list[str],
    executed_tools: list[str],
    tool_results: list[InvestigationToolResult],
    llm_provider,
    round_index: int,
    max_rounds: int,
) -> InvestigationTermination | None:
    system_prompt, user_prompt = build_investigation_termination_prompt(
        context,
        diagnosis,
        rule_termination=rule_termination.model_dump(),
        remaining_tools=remaining_tools,
        executed_tools=executed_tools,
        tool_results=tool_results,
        round_index=round_index,
        max_rounds=max_rounds,
    )
    try:
        raw = llm_provider.complete_json(system_prompt, user_prompt)
    except Exception:
        return None

    status = raw.get("status")
    confidence = raw.get("confidence")
    if status not in {"continue", "completed"}:
        return None
    if confidence not in {"high", "medium", "low"}:
        return None

    next_actions = [item for item in raw.get("next_actions", []) if isinstance(item, str) and item.strip()]
    return InvestigationTermination(
        status=status,
        reason=str(raw.get("reason") or rule_termination.reason),
        confidence=confidence,
        source="llm",
        reasoning=str(raw.get("reasoning") or ""),
        next_actions=next_actions or list(rule_termination.next_actions),
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
                tool_names=_preferred_tools(available_tools, "scope_overview", "signal_focus", "frame_targeting", "knowledge_refs"),
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
                tool_names=_preferred_tools(available_tools, "scope_overview", "signal_focus", "evidence_focus", "visibility_analysis", "protocol_drilldown", "frame_targeting"),
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
                tool_names=_preferred_tools(available_tools, "visibility_analysis", "evidence_focus", "signal_focus", "protocol_drilldown", "frame_targeting", "knowledge_refs"),
            )
        ]

    return [
        InvestigationHypothesis(
            hypothesis_id=f"{context.scope.scope_id}:success-path",
            statement="successful_control_plane_sequence",
            priority="medium",
            rationale=diagnosis.summary or "scope appears healthy",
            tool_names=_preferred_tools(available_tools, "scope_overview", "signal_focus", "evidence_focus", "protocol_drilldown", "frame_targeting"),
        )
    ]


def _build_tool_sequence(
    hypotheses: list[InvestigationHypothesis],
    available_tools: list[str],
    *,
    diagnosis: ScopeDiagnosis | None,
    round_index: int,
    max_rounds: int,
) -> list[str]:
    sequence: list[str] = []
    for hypothesis in hypotheses:
        for tool_name in hypothesis.tool_names:
            if tool_name in available_tools and tool_name not in sequence:
                sequence.append(tool_name)
    for fallback in ["scope_overview", "evidence_focus", "knowledge_refs"]:
        if fallback in available_tools and fallback not in sequence:
            sequence.append(fallback)
    limit = _tool_limit(diagnosis, round_index, max_rounds, len(sequence))
    return sequence[:limit]


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


def _tool_limit(
    diagnosis: ScopeDiagnosis | None,
    round_index: int,
    max_rounds: int,
    available_count: int,
) -> int:
    if round_index >= max_rounds:
        return available_count
    if diagnosis is None:
        return min(2, available_count)
    if diagnosis.verdict in {"FAIL", "INCONCLUSIVE"}:
        return min(2, available_count)
    return min(3, available_count)


def _rank_with_llm(
    context: DiagnosisContext,
    diagnosis: ScopeDiagnosis | None,
    hypotheses: list[InvestigationHypothesis],
    available_tools: list[str],
    previous_results: list[InvestigationToolResult],
    *,
    llm_provider,
    round_index: int,
    max_rounds: int,
) -> dict[str, Any] | None:
    system_prompt, user_prompt = build_investigation_planner_prompt(
        context,
        diagnosis,
        hypothesis_specs=[item.model_dump() for item in hypotheses],
        available_tools=available_tools,
        previous_results=previous_results,
        round_index=round_index,
        max_rounds=max_rounds,
    )
    try:
        raw = llm_provider.complete_json(system_prompt, user_prompt)
    except Exception:
        return None

    ranked_ids = [item for item in raw.get("hypothesis_order", []) if isinstance(item, str)]
    ranked_tools = [item for item in raw.get("tool_sequence", []) if isinstance(item, str) and item in available_tools]

    if not ranked_ids and not ranked_tools:
        return None

    hypothesis_map = {item.hypothesis_id: item for item in hypotheses}
    ordered_hypotheses = [hypothesis_map[item] for item in ranked_ids if item in hypothesis_map]
    ordered_hypotheses.extend(item for item in hypotheses if item.hypothesis_id not in {h.hypothesis_id for h in ordered_hypotheses})

    fallback_tools = _build_tool_sequence(
        ordered_hypotheses,
        available_tools,
        diagnosis=diagnosis,
        round_index=round_index,
        max_rounds=max_rounds,
    )
    ordered_tools = []
    for item in ranked_tools:
        if item not in ordered_tools:
            ordered_tools.append(item)
    for item in fallback_tools:
        if item not in ordered_tools:
            ordered_tools.append(item)

    limit = _tool_limit(diagnosis, round_index, max_rounds, len(ordered_tools))
    return {
        "hypotheses": ordered_hypotheses,
        "tool_sequence": ordered_tools[:limit],
    }


def _merge_actions(base: list[str], diagnosis: ScopeDiagnosis | None) -> list[str]:
    actions = list(base)
    if diagnosis is not None and diagnosis.failure_point:
        actions.append(f"inspect evidence around failure point {diagnosis.failure_point}")
    if diagnosis is not None and diagnosis.root_cause:
        actions.append(f"verify root cause hypothesis {diagnosis.root_cause}")
    if not actions:
        actions.append("review scope timeline and key evidence for confirmation")
    return actions
