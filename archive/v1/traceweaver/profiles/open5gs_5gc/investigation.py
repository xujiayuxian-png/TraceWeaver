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
            CallableInvestigationTool(
                name="protocol_drilldown",
                description="Drill down into protocol layers, events, and child scopes relevant to the current hypothesis",
                handler=_protocol_drilldown_tool,
            ),
            CallableInvestigationTool(
                name="frame_targeting",
                description="Return the most relevant frames to inspect next",
                handler=_frame_targeting_tool,
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


def _protocol_drilldown_tool(
    context: DiagnosisContext,
    diagnosis: ScopeDiagnosis | None,
    hypothesis: str | None,
) -> InvestigationToolResult:
    protocol_counts: dict[str, int] = {}
    for record in context.scope.records:
        protocol_counts[record.primary_protocol] = protocol_counts.get(record.primary_protocol, 0) + 1

    child_summaries = [
        {
            "scope_id": child.scope_id,
            "scope_type": child.scope_type,
            "event_count": len(child.events),
            "record_count": len(child.records),
        }
        for child in context.scope.children
    ]
    event_types = sorted({event.event_type for event in context.scope.events})
    target_protocols = _target_protocols(diagnosis, hypothesis)

    return InvestigationToolResult(
        tool_name="protocol_drilldown",
        summary=f"protocols={len(protocol_counts)} target_protocols={len(target_protocols)} child_scopes={len(child_summaries)}",
        details={
            "protocol_counts": protocol_counts,
            "target_protocols": target_protocols,
            "event_types": event_types,
            "child_scopes": child_summaries,
            "hypothesis": hypothesis,
        },
        evidence_refs=[item.evidence_id for item in context.evidence if any(support in {"registration_chain", "sbi_correlation", "pdu_correlation"} for support in item.supports)],
    )


def _frame_targeting_tool(
    context: DiagnosisContext,
    diagnosis: ScopeDiagnosis | None,
    hypothesis: str | None,
) -> InvestigationToolResult:
    ranked_frames: list[tuple[int, int, str]] = []

    for signal in context.signals:
        if signal.frame_number is None:
            continue
        score = 0
        if diagnosis is not None and diagnosis.failure_point:
            failure_point = diagnosis.failure_point.lower()
            if failure_point.startswith("authentication") and "AUTH" in signal.name:
                score += 4
            elif failure_point.startswith("registration") and ("REGISTRATION" in signal.name or signal.category == "ngap"):
                score += 4
            elif failure_point.startswith("pdu") and signal.category in {"session_management", "pfcp", "sbi"}:
                score += 4
        if hypothesis and hypothesis.lower() in signal.name.lower():
            score += 2
        if signal.category in {"sbi", "pfcp", "ngap", "session_management"}:
            score += 1
        ranked_frames.append((score, signal.frame_number, signal.name))

    for evidence in context.evidence:
        for frame_number in evidence.frame_numbers[:5]:
            ranked_frames.append((1, frame_number, evidence.evidence_id))

    ranked_frames.sort(key=lambda item: (-item[0], item[1], item[2]))
    selected = []
    seen_frames: set[int] = set()
    for score, frame_number, source in ranked_frames:
        if frame_number in seen_frames:
            continue
        seen_frames.add(frame_number)
        selected.append({"frame_number": frame_number, "score": score, "source": source})
        if len(selected) >= 8:
            break

    return InvestigationToolResult(
        tool_name="frame_targeting",
        summary=f"target_frames={len(selected)}",
        details={
            "frames": selected,
            "hypothesis": hypothesis,
        },
        evidence_refs=[item.evidence_id for item in context.evidence if any(frame["frame_number"] in item.frame_numbers for frame in selected)],
    )


def _target_protocols(
    diagnosis: ScopeDiagnosis | None,
    hypothesis: str | None,
) -> list[str]:
    if diagnosis is not None and diagnosis.failure_point:
        failure_point = diagnosis.failure_point.lower()
        if failure_point.startswith("authentication"):
            return ["nas_5gmm", "ngap", "http2"]
        if failure_point.startswith("registration"):
            return ["nas_5gmm", "ngap", "http2"]
        if failure_point.startswith("pdu"):
            return ["nas_5gsm", "http2", "pfcp"]
    if hypothesis and "visibility" in hypothesis.lower():
        return ["ngap", "http2", "pfcp"]
    return ["ngap", "http2", "pfcp", "nas_5gs"]
