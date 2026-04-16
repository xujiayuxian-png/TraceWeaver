from __future__ import annotations

from pathlib import Path

from traceweaver.core.analysis.options import AnalysisOptions
from traceweaver.core.contracts import AnalysisScope, CaptureRecord, DiagnosisContext, DiagnosticSignal, EvidenceItem, ScopeDiagnosis, StructuredEvent, VisibilityAssessment
from traceweaver.profiles.open5gs_5gc.domain.pdu import PDUSessionFlow
from traceweaver.profiles.open5gs_5gc.domain.records import ExtractedRecordSet, NormalizedRecord
from traceweaver.profiles.open5gs_5gc.domain.diagnosis import DiagnosticSignal as LegacyDiagnosticSignal
from traceweaver.profiles.open5gs_5gc.domain.diagnosis import SessionDiagnosis
from traceweaver.profiles.open5gs_5gc.domain.sessions import UESession
from traceweaver.profiles.open5gs_5gc.investigation import build_investigation_tool_registry as build_tool_registry
from traceweaver.profiles.open5gs_5gc.assemble import build_pdu_sessions_for_ue, correlate_pfcp_to_pdu, correlate_sbi_to_sessions, group_ue_sessions, pair_sbi_calls
from traceweaver.profiles.open5gs_5gc.diagnosis import collect_signals, diagnose_session, llm_diagnose_session
from traceweaver.profiles.open5gs_5gc.extract import extract_records
from traceweaver.profiles.open5gs_5gc.runtime import Open5GSAnalysisRuntime


class Open5GS5GCProfile:
    name = "open5gs_5gc"
    description = "Open5GS-oriented 5GC registration and PDU session diagnosis profile"
    knowledge_refs = [
        "open5gs_5gc:registration_chain",
        "open5gs_5gc:sbi_correlation",
        "open5gs_5gc:pfcp_visibility",
    ]

    def extract(
        self,
        path: str,
        *,
        options: AnalysisOptions,
    ) -> Open5GSAnalysisRuntime:
        record_set = extract_records(
            Path(path),
            display_filter=options.display_filter,
            decode_as=options.decode_as or None,
            limit=options.record_limit,
        )
        return Open5GSAnalysisRuntime(
            record_set=record_set,
            warnings=list(record_set.warnings),
        )

    def build_scopes(
        self,
        runtime: Open5GSAnalysisRuntime,
        *,
        options: AnalysisOptions,
    ) -> list[AnalysisScope]:
        if options.scope_limit is not None and options.scope_limit <= 0:
            raise ValueError("scope_limit must be > 0")

        records = runtime.record_set
        warnings = runtime.warnings
        sessions = group_ue_sessions(records, warnings=warnings)
        correlate_sbi_to_sessions(pair_sbi_calls(records), sessions, warnings=warnings)

        for session in sessions:
            session.pdu_sessions = build_pdu_sessions_for_ue(session)
            correlate_pfcp_to_pdu(records, session.pdu_sessions, warnings=warnings)
            session.pdu_session_count = len(session.pdu_sessions)

        if options.scope_limit is not None and len(sessions) > options.scope_limit:
            warnings.append(
                f"scope_limit_applied: returning {options.scope_limit} of {len(sessions)} assembled scopes"
            )
            sessions = sessions[: options.scope_limit]

        runtime.sessions = sessions
        runtime.session_index = {session.session_id: session for session in sessions}
        runtime.signal_cache = {}
        return [_scope_from_ue_session(session) for session in sessions]

    def annotate_signals(
        self,
        scope: AnalysisScope,
        runtime: Open5GSAnalysisRuntime,
        *,
        options: AnalysisOptions,
    ) -> list[DiagnosticSignal]:
        session = runtime.session_index[scope.scope_id]
        legacy_signals = collect_signals(session, runtime.record_set)
        runtime.signal_cache[scope.scope_id] = legacy_signals
        return [_signal_from_legacy(scope.scope_id, item) for item in legacy_signals]

    def assess_visibility(
        self,
        scope: AnalysisScope,
        runtime: Open5GSAnalysisRuntime,
        signals: list[DiagnosticSignal],
        *,
        options: AnalysisOptions,
    ) -> VisibilityAssessment:
        session = runtime.session_index[scope.scope_id]
        return _build_visibility(scope, signals, session=session, records=runtime.record_set)

    def collect_evidence(
        self,
        scope: AnalysisScope,
        runtime: Open5GSAnalysisRuntime,
        signals: list[DiagnosticSignal],
        visibility: VisibilityAssessment | None,
        *,
        options: AnalysisOptions,
    ) -> list[EvidenceItem]:
        session = runtime.session_index[scope.scope_id]
        return _build_evidence(scope, session, signals)

    def diagnose_scope(
        self,
        scope: AnalysisScope,
        runtime: Open5GSAnalysisRuntime,
        signals: list[DiagnosticSignal],
        visibility: VisibilityAssessment | None,
        *,
        llm_provider=None,
        options: AnalysisOptions,
    ) -> ScopeDiagnosis:
        _record_diagnosis_engine(runtime, llm_provider)
        session = runtime.session_index[scope.scope_id]
        legacy_signals = runtime.signal_cache.get(scope.scope_id)
        if legacy_signals is None:
            legacy_signals = collect_signals(session, runtime.record_set)
            runtime.signal_cache[scope.scope_id] = legacy_signals

        if llm_provider is not None:
            diagnosis = llm_diagnose_session(session, legacy_signals, llm_provider)
        else:
            diagnosis = diagnose_session(session, legacy_signals)

        if visibility is not None:
            diagnosis = _apply_visibility_constraints(diagnosis, visibility)
        return _scope_diagnosis_from_legacy(diagnosis)

    def build_investigation_tool_registry(
        self,
        context: DiagnosisContext,
        diagnosis: ScopeDiagnosis | None,
    ):
        return build_tool_registry(context, diagnosis)


def _scope_from_ue_session(session: UESession) -> AnalysisScope:
    return AnalysisScope(
        scope_id=session.session_id,
        scope_type="ue_session",
        display_name=session.session_id,
        start_time_epoch=session.start_time_epoch,
        end_time_epoch=session.end_time_epoch,
        attributes={
            "ran_ue_ngap_id": session.ran_ue_ngap_id,
            "amf_ue_ngap_id": session.amf_ue_ngap_id,
            "suci": session.suci,
            "supi": session.supi,
            "source_record_count": session.source_record_count,
            "event_count": session.event_count,
            "sbi_call_count": session.sbi_call_count,
            "pdu_session_count": session.pdu_session_count,
        },
        records=[_record_from_legacy(record) for record in session.records],
        events=[_event_from_legacy(event) for event in session.events],
        children=[_scope_from_pdu_session(pdu) for pdu in session.pdu_sessions],
        related_entities={
            "frame_numbers": [str(frame) for frame in session.frame_numbers],
        },
    )


def _scope_from_pdu_session(flow: PDUSessionFlow) -> AnalysisScope:
    return AnalysisScope(
        scope_id=f"pdu:{flow.parent_session_id or 'unknown'}:{flow.pdu_session_id}",
        scope_type="pdu_session",
        display_name=f"PDU Session {flow.pdu_session_id}",
        start_time_epoch=flow.start_time_epoch,
        end_time_epoch=flow.end_time_epoch,
        attributes={
            "parent_session_id": flow.parent_session_id,
            "pdu_session_id": flow.pdu_session_id,
            "event_count": flow.event_count,
            "sbi_call_count": flow.sbi_call_count,
            "pfcp_flow_count": flow.pfcp_flow_count,
            "smf_ips": list(flow.smf_ips),
        },
        events=[_event_from_legacy(event) for event in flow.events],
        related_entities={
            "pfcp_frames": [str(item.frame_number) for item in flow.pfcp_flows],
            "sbi_paths": [item.path or "" for item in flow.sbi_calls if item.path],
        },
    )


def _record_from_legacy(record: NormalizedRecord) -> CaptureRecord:
    return CaptureRecord(
        frame_number=record.frame_number,
        time_epoch=record.time_epoch,
        time_relative=record.time_relative,
        primary_protocol=record.primary_protocol or "",
        protocol_layers=list(record.protocols),
        src_ip=record.src_ip or "",
        dst_ip=record.dst_ip or "",
        src_port=record.src_port,
        dst_port=record.dst_port,
        connection_key=_connection_key(record),
        fields=dict(record.fields),
    )


def _event_from_legacy(event) -> StructuredEvent:
    return StructuredEvent(
        event_id=f"frame-{event.frame_number}:{event.event_name}",
        event_type=event.event_name,
        protocol=event.protocol,
        time_epoch=event.time_epoch,
        frame_number=event.frame_number,
        key_fields={
            "message_type": event.message_type,
            "cause": event.cause,
            "pdu_session_id": event.pdu_session_id,
        },
        attributes={
            "ran_ue_ngap_id": event.ran_ue_ngap_id,
            "amf_ue_ngap_id": event.amf_ue_ngap_id,
            "src_ip": event.src_ip,
            "dst_ip": event.dst_ip,
        },
    )


def _scope_diagnosis_from_legacy(diagnosis: SessionDiagnosis) -> ScopeDiagnosis:
    return ScopeDiagnosis(
        scope_id=diagnosis.session_id,
        scope_type="ue_session",
        verdict=diagnosis.verdict,
        failure_point=diagnosis.failure_point,
        root_cause=diagnosis.root_cause,
        confidence=diagnosis.confidence,
        signal_names=list(diagnosis.signal_names),
        sbi_paths=list(diagnosis.sbi_paths),
        notes=list(diagnosis.notes),
        summary=_diagnosis_summary(diagnosis),
    )


def _signal_from_legacy(scope_id: str, signal: LegacyDiagnosticSignal) -> DiagnosticSignal:
    frame_number = signal.frame_number
    signal_id = f"{scope_id}:{signal.name}:{frame_number if frame_number is not None else 'na'}"
    return DiagnosticSignal(
        signal_id=signal_id,
        name=signal.name,
        scope_id=scope_id,
        source=signal.source,
        category=_signal_category(signal.name),
        confidence="high",
        summary=signal.name,
        frame_number=frame_number,
        time_epoch=signal.time_epoch,
        details=dict(signal.details),
        evidence_refs=[f"{scope_id}:signal:{signal.name}"],
    )


def _build_visibility(
    scope: AnalysisScope,
    signals: list[DiagnosticSignal],
    *,
    session: UESession,
    records: ExtractedRecordSet,
) -> VisibilityAssessment:
    signal_names = {item.name for item in signals}
    missing_segments: list[str] = []
    weak_links: list[str] = []
    warnings: list[str] = []

    if "NGAP_VISIBLE" not in signal_names:
        missing_segments.append("ngap")
    if "SBI_HTTP2_VISIBLE" not in signal_names:
        weak_links.append("sbi_http2")
    if "PFCP_VISIBLE" not in signal_names:
        weak_links.append("pfcp")
    if "PARTIAL_CAPTURE_NO_PFCP" in signal_names:
        missing_segments.append("pfcp")
        warnings.append("PFCP traffic not visible in capture")
    if "LOW_RECORD_COUNT" in signal_names:
        warnings.append("very small record set may indicate truncated capture")
    if _scope_reaches_capture_tail(session, records):
        weak_links.append("capture_tail")
        warnings.append("capture ends immediately after scope evidence; success inference may be incomplete")

    completeness = "complete"
    if missing_segments:
        completeness = "partial"
    elif weak_links:
        completeness = "limited"

    return VisibilityAssessment(
        scope_id=scope.scope_id,
        completeness=completeness,
        missing_segments=missing_segments,
        weak_links=weak_links,
        warnings=warnings,
    )


def _apply_visibility_constraints(
    diagnosis: SessionDiagnosis,
    visibility: VisibilityAssessment,
) -> SessionDiagnosis:
    notes = list(diagnosis.notes)
    for warning in visibility.warnings:
        note = f"visibility_warning: {warning}"
        if note not in notes:
            notes.append(note)

    success_like_verdict = diagnosis.verdict in {"OK", "FAIL_THEN_OK"}
    low_record_warning = any("truncated capture" in warning for warning in visibility.warnings)
    capture_tail_warning = any("success inference may be incomplete" in warning for warning in visibility.warnings)
    explicit_registration_success = "REGISTRATION_ACCEPT" in diagnosis.signal_names or "REGISTRATION_COMPLETE" in diagnosis.signal_names

    if success_like_verdict and low_record_warning:
        override_note = "visibility_override: success downgraded because capture may be truncated"
        if override_note not in notes:
            notes.append(override_note)
        return diagnosis.model_copy(
            update={
                "verdict": "INCONCLUSIVE",
                "failure_point": "UNKNOWN_DUE_TO_TRUNCATION",
                "root_cause": "capture_stopped_early",
                "confidence": "medium",
                "notes": notes,
            }
        )

    if success_like_verdict and capture_tail_warning and not explicit_registration_success:
        override_note = "visibility_override: inferred success downgraded because capture ends at scope tail"
        if override_note not in notes:
            notes.append(override_note)
        return diagnosis.model_copy(
            update={
                "verdict": "INCONCLUSIVE",
                "failure_point": "UNKNOWN_DUE_TO_TRUNCATION",
                "root_cause": "capture_ended_before_success_could_be_confirmed",
                "confidence": "medium",
                "notes": notes,
            }
        )

    if success_like_verdict and visibility.completeness == "partial":
        override_note = "visibility_override: success downgraded because capture is partial"
        if override_note not in notes:
            notes.append(override_note)
        return diagnosis.model_copy(
            update={
                "verdict": "INCONCLUSIVE",
                "failure_point": None,
                "root_cause": "capture_missing_segments",
                "confidence": "medium",
                "notes": notes,
            }
        )

    if notes != diagnosis.notes:
        return diagnosis.model_copy(update={"notes": notes})

    return diagnosis


def _scope_reaches_capture_tail(session: UESession, records: ExtractedRecordSet) -> bool:
    if not records.records or session.end_time_epoch is None:
        return False
    capture_end = records.records[-1].time_epoch
    return abs(capture_end - session.end_time_epoch) <= 0.001


def _build_evidence(
    scope: AnalysisScope,
    session: UESession,
    signals: list[DiagnosticSignal],
) -> list[EvidenceItem]:
    evidence: list[EvidenceItem] = []
    if session.events:
        evidence.append(
            EvidenceItem(
                evidence_id=f"{scope.scope_id}:timeline:nas",
                scope_id=scope.scope_id,
                source_type="timeline",
                source_name="nas_events",
                summary=f"{len(session.events)} NAS/NGAP events attached to scope",
                frame_numbers=[event.frame_number for event in session.events],
                attributes={"event_names": [event.event_name for event in session.events]},
                supports=["registration_chain"],
            )
        )
    if session.sbi_calls:
        evidence.append(
            EvidenceItem(
                evidence_id=f"{scope.scope_id}:timeline:sbi",
                scope_id=scope.scope_id,
                source_type="timeline",
                source_name="sbi_calls",
                summary=f"{len(session.sbi_calls)} SBI calls correlated to scope",
                frame_numbers=[call.request_frame for call in session.sbi_calls if call.request_frame is not None],
                attributes={"paths": [call.path for call in session.sbi_calls if call.path]},
                supports=["sbi_correlation"],
            )
        )
    if session.pdu_sessions:
        evidence.append(
            EvidenceItem(
                evidence_id=f"{scope.scope_id}:timeline:pdu",
                scope_id=scope.scope_id,
                source_type="timeline",
                source_name="pdu_sessions",
                summary=f"{len(session.pdu_sessions)} PDU sessions assembled",
                frame_numbers=[event.frame_number for flow in session.pdu_sessions for event in flow.events],
                attributes={"pdu_session_ids": [flow.pdu_session_id for flow in session.pdu_sessions]},
                supports=["pdu_correlation"],
            )
        )
    if signals:
        evidence.append(
            EvidenceItem(
                evidence_id=f"{scope.scope_id}:signal:summary",
                scope_id=scope.scope_id,
                source_type="signal_summary",
                source_name="diagnostic_signals",
                summary=f"{len(signals)} diagnostic signals extracted",
                frame_numbers=[item.frame_number for item in signals if item.frame_number is not None],
                attributes={"signal_names": [item.name for item in signals]},
                supports=["diagnostic_signal_set"],
            )
        )
    return evidence


def _record_diagnosis_engine(runtime: Open5GSAnalysisRuntime, llm_provider) -> None:
    if llm_provider is not None:
        marker = f"diagnosis_engine: llm ({llm_provider.config.model})"
    else:
        marker = "diagnosis_engine: rule"
    if marker not in runtime.warnings:
        runtime.warnings.append(marker)


def _signal_category(name: str) -> str:
    if name.startswith("SBI_"):
        return "sbi"
    if name.startswith("PFCP_"):
        return "pfcp"
    if name.startswith("NGAP_"):
        return "ngap"
    if name.startswith("PDU_") or name.startswith("T3580"):
        return "session_management"
    return "mobility"


def _diagnosis_summary(diagnosis: SessionDiagnosis) -> str:
    parts = [diagnosis.verdict]
    if diagnosis.failure_point:
        parts.append(diagnosis.failure_point)
    if diagnosis.root_cause:
        parts.append(diagnosis.root_cause)
    return " | ".join(parts)


def _connection_key(record: NormalizedRecord) -> str:
    src = f"{record.src_ip}:{record.src_port}" if record.src_ip and record.src_port is not None else (record.src_ip or "")
    dst = f"{record.dst_ip}:{record.dst_port}" if record.dst_ip and record.dst_port is not None else (record.dst_ip or "")
    return "|".join(item for item in sorted([src, dst]) if item)
