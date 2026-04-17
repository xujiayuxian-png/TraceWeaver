from __future__ import annotations

from traceweaver.core.agent.tools import InvestigationToolResult
from traceweaver.core.contracts import DiagnosisContext, ScopeDiagnosis

PLANNER_SYSTEM_PROMPT = """\
You are an investigation planner for TraceWeaver.
You receive a structured diagnosis context, an optional current diagnosis, the tools still available in this round, and prior tool outputs.
Your job is to rank investigation hypotheses and choose the next best tools for this round.

Rules:
- Only use hypothesis ids and tool names that are provided in the input.
- Prefer narrower, higher-signal tools before broad summary tools when the diagnosis is FAIL or INCONCLUSIVE.
- If visibility is partial, prioritize visibility or frame targeting tools.
- If the diagnosis is already OK with high confidence, choose only lightweight confirmation tools.
- Return strictly valid JSON.
"""

TERMINATION_SYSTEM_PROMPT = """\
You are an investigation termination reviewer for TraceWeaver.
You receive the current diagnosis context, the current diagnosis, completed tool outputs, remaining tools, and a rule-based termination proposal.
Your job is to reconsider whether investigation should continue, and synthesize the best next actions.

Rules:
- Respect the available evidence and tool outputs. Do not invent missing packets or frames.
- Only choose status from: continue, completed.
- Confidence must be one of: high, medium, low.
- If there are still high-value remaining tools and the current evidence is weak or incomplete, prefer continue.
- If the investigation is already sufficiently supported, choose completed and synthesize concise next actions.
- Return strictly valid JSON.
"""


def build_investigation_planner_prompt(
    context: DiagnosisContext,
    diagnosis: ScopeDiagnosis | None,
    *,
    hypothesis_specs: list[dict],
    available_tools: list[str],
    previous_results: list[InvestigationToolResult],
    round_index: int,
    max_rounds: int,
) -> tuple[str, str]:
    user_lines: list[str] = []
    user_lines.append(f"scope_id: {context.scope.scope_id}")
    user_lines.append(f"scope_type: {context.scope.scope_type}")
    user_lines.append(f"round_index: {round_index}")
    user_lines.append(f"max_rounds: {max_rounds}")
    user_lines.append(f"visibility: {context.visibility.completeness if context.visibility else 'unknown'}")
    user_lines.append(f"signal_count: {len(context.signals)}")
    user_lines.append(f"evidence_count: {len(context.evidence)}")
    if diagnosis is not None:
        user_lines.append(f"diagnosis_verdict: {diagnosis.verdict}")
        user_lines.append(f"diagnosis_failure_point: {diagnosis.failure_point}")
        user_lines.append(f"diagnosis_root_cause: {diagnosis.root_cause}")
        user_lines.append(f"diagnosis_confidence: {diagnosis.confidence}")
        user_lines.append(f"diagnosis_summary: {diagnosis.summary}")
    else:
        user_lines.append("diagnosis_verdict: none")

    user_lines.append("")
    user_lines.append("candidate_hypotheses:")
    for item in hypothesis_specs:
        user_lines.append(
            f"- id={item['hypothesis_id']} statement={item['statement']} priority={item['priority']} rationale={item['rationale']} tool_names={','.join(item['tool_names'])}"
        )

    user_lines.append("")
    user_lines.append("available_tools:")
    for name in available_tools:
        user_lines.append(f"- {name}")

    user_lines.append("")
    user_lines.append("previous_tool_results:")
    if previous_results:
        for result in previous_results[-8:]:
            user_lines.append(f"- {result.tool_name}: {result.summary}")
    else:
        user_lines.append("- none")

    user_lines.append("")
    user_lines.append(
        "planner_response_schema: {\"hypothesis_order\": [\"id\"], \"tool_sequence\": [\"tool\"], \"stop_when\": \"string\", \"reasoning\": \"short string\"}"
    )
    return PLANNER_SYSTEM_PROMPT, "\n".join(user_lines)


def build_investigation_termination_prompt(
    context: DiagnosisContext,
    diagnosis: ScopeDiagnosis | None,
    *,
    rule_termination: dict,
    remaining_tools: list[str],
    executed_tools: list[str],
    tool_results: list[InvestigationToolResult],
    round_index: int,
    max_rounds: int,
) -> tuple[str, str]:
    user_lines: list[str] = []
    user_lines.append(f"scope_id: {context.scope.scope_id}")
    user_lines.append(f"scope_type: {context.scope.scope_type}")
    user_lines.append(f"round_index: {round_index}")
    user_lines.append(f"max_rounds: {max_rounds}")
    user_lines.append(f"visibility: {context.visibility.completeness if context.visibility else 'unknown'}")
    user_lines.append(f"executed_tools: {','.join(executed_tools) if executed_tools else 'none'}")
    user_lines.append(f"remaining_tools: {','.join(remaining_tools) if remaining_tools else 'none'}")
    if diagnosis is not None:
        user_lines.append(f"diagnosis_verdict: {diagnosis.verdict}")
        user_lines.append(f"diagnosis_failure_point: {diagnosis.failure_point}")
        user_lines.append(f"diagnosis_root_cause: {diagnosis.root_cause}")
        user_lines.append(f"diagnosis_confidence: {diagnosis.confidence}")
        user_lines.append(f"diagnosis_summary: {diagnosis.summary}")
    else:
        user_lines.append("diagnosis_verdict: none")

    user_lines.append("")
    user_lines.append("rule_termination:")
    user_lines.append(str(rule_termination))

    user_lines.append("")
    user_lines.append("recent_tool_results:")
    if tool_results:
        for result in tool_results[-8:]:
            user_lines.append(f"- round={result.round_index} tool={result.tool_name} summary={result.summary}")
    else:
        user_lines.append("- none")

    user_lines.append("")
    user_lines.append(
        "termination_reconsideration_schema: {\"status\": \"continue|completed\", \"reason\": \"string\", \"confidence\": \"high|medium|low\", \"next_actions\": [\"action\"], \"reasoning\": \"short string\"}"
    )
    return TERMINATION_SYSTEM_PROMPT, "\n".join(user_lines)
