from __future__ import annotations

from traceweaver.core.agent.tools import CallableInvestigationTool, InvestigationToolRegistry, InvestigationToolResult, build_default_tool_registry
from traceweaver.core.contracts import DiagnosisContext, ScopeDiagnosis


def build_investigation_tool_registry(
    context: DiagnosisContext,
    diagnosis: ScopeDiagnosis | None,
) -> InvestigationToolRegistry:
    registry = build_default_tool_registry()
    registry.extend(
        [
            CallableInvestigationTool(
                name="scope_overview",
                description="Summarize scope identifiers, counters, and time range",
                handler=_scope_overview_tool,
            ),
            CallableInvestigationTool(
                name="visibility_analysis",
                description="Summarize capture completeness and protocol visibility gaps",
                handler=_visibility_analysis_tool,
            ),
            CallableInvestigationTool(
                name="evidence_focus",
                description="Select evidence most relevant to the current diagnosis or hypothesis",
                handler=_evidence_focus_tool,
            ),
            CallableInvestigationTool(
                name="signal_focus",
                description="Select signal names most relevant to the current diagnosis or hypothesis",
                handler=_signal_focus_tool,
            ),
        ]
    )
    return registry


def _scope_overview_tool(
    context: DiagnosisContext,
    diagnosis: ScopeDiagnosis | None,
    hypothesis: str | None,
) -> InvestigationToolResult:
    return InvestigationToolResult(
        tool_name="scope_overview",
        summary=f"scope={context.scope.scope_type} records={len(context.scope.records)} events={len(context.scope.events)}",
        details={
            "scope_id": context.scope.scope_id,
            "scope_type": context.scope.scope_type,
            "display_name": context.scope.display_name,
            "attributes": dict(context.scope.attributes),
            "start_time_epoch": context.scope.start_time_epoch,
            "end_time_epoch": context.scope.end_time_epoch,
            "hypothesis": hypothesis,
            "diagnosis_verdict": diagnosis.verdict if diagnosis is not None else None,
        },
    )


def _visibility_analysis_tool(
    context: DiagnosisContext,
    diagnosis: ScopeDiagnosis | None,
    hypothesis: str | None,
) -> InvestigationToolResult:
    visibility = context.visibility
    if visibility is None:
        return InvestigationToolResult(
            tool_name="visibility_analysis",
            summary="visibility unavailable",
            details={"hypothesis": hypothesis},
        )
    return InvestigationToolResult(
        tool_name="visibility_analysis",
        summary=f"visibility={visibility.completeness}",
        details={
            "completeness": visibility.completeness,
            "missing_segments": list(visibility.missing_segments),
            "weak_links": list(visibility.weak_links),
            "warnings": list(visibility.warnings),
            "hypothesis": hypothesis,
        },
    )


def _evidence_focus_tool(
    context: DiagnosisContext,
    diagnosis: ScopeDiagnosis | None,
    hypothesis: str | None,
) -> InvestigationToolResult:
    focused = []
    for item in context.evidence:
        score = 0
        if diagnosis is not None and diagnosis.failure_point:
            fp = diagnosis.failure_point.lower()
            if fp in item.summary.lower():
                score += 2
            if any(fp in str(value).lower() for value in item.attributes.values()):
                score += 1
        if hypothesis and hypothesis.lower() in item.summary.lower():
            score += 2
        if item.supports:
            score += 1
        focused.append((score, item))
    focused.sort(key=lambda pair: (-pair[0], pair[1].evidence_id))
    selected = [item for _, item in focused[:3]]
    return InvestigationToolResult(
        tool_name="evidence_focus",
        summary=f"focused_evidence={len(selected)}",
        details={
            "selected_evidence": [
                {
                    "evidence_id": item.evidence_id,
                    "summary": item.summary,
                    "supports": list(item.supports),
                }
                for item in selected
            ],
            "hypothesis": hypothesis,
        },
        evidence_refs=[item.evidence_id for item in selected],
    )


def _signal_focus_tool(
    context: DiagnosisContext,
    diagnosis: ScopeDiagnosis | None,
    hypothesis: str | None,
) -> InvestigationToolResult:
    selected = []
    for signal in context.signals:
        score = 0
        if diagnosis is not None and diagnosis.failure_point:
            failure_point = diagnosis.failure_point.lower()
            if failure_point.startswith("authentication") and "AUTH" in signal.name:
                score += 3
            if failure_point.startswith("registration") and ("REGISTRATION" in signal.name or signal.category == "ngap"):
                score += 3
            if failure_point.startswith("pdu") and (signal.category in {"session_management", "pfcp", "sbi"}):
                score += 3
        if hypothesis and hypothesis.lower() in signal.name.lower():
            score += 2
        if signal.category in {"sbi", "pfcp", "session_management"}:
            score += 1
        if score > 0:
            selected.append((score, signal))
    selected.sort(key=lambda pair: (-pair[0], pair[1].signal_id))
    top = [item for _, item in selected[:8]] or context.signals[:8]
    return InvestigationToolResult(
        tool_name="signal_focus",
        summary=f"focused_signals={len(top)}",
        details={
            "signal_names": [item.name for item in top],
            "frames": [item.frame_number for item in top],
            "hypothesis": hypothesis,
        },
        evidence_refs=[ref for item in top for ref in item.evidence_refs],
    )
