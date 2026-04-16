from __future__ import annotations

from pathlib import Path

from traceweaver.core.analysis.options import AnalysisOptions
from traceweaver.core.analysis.result import AnalysisResult
from traceweaver.core.contracts import AnalysisScope, CaptureRecord, DiagnosticSignal, ScopeDiagnosis, StructuredEvent
from traceweaver.models import ExtractedRecordSet, NormalizedRecord, PDUSessionFlow, SessionDiagnosis, UESession
from traceweaver.profiles.open5gs_5gc.assemble import build_pdu_sessions_for_ue, correlate_pfcp_to_pdu, correlate_sbi_to_sessions, group_ue_sessions, pair_sbi_calls
from traceweaver.profiles.open5gs_5gc.diagnosis import collect_signals, diagnose_session, llm_diagnose_session
from traceweaver.profiles.open5gs_5gc.extract import extract_records


class Open5GS5GCProfile:
    name = "open5gs_5gc"
    description = "Open5GS-oriented 5GC registration and PDU session diagnosis profile"

    def analyze_capture(
        self,
        path: str,
        *,
        options: AnalysisOptions,
        llm_provider=None,
    ) -> AnalysisResult:
        records = extract_records(
            Path(path),
            display_filter=options.display_filter,
            decode_as=options.decode_as or None,
            limit=options.limit,
        )
        warnings = list(records.warnings)
        sessions = group_ue_sessions(records, warnings=warnings)
        correlate_sbi_to_sessions(pair_sbi_calls(records), sessions, warnings=warnings)

        for session in sessions:
            session.pdu_sessions = build_pdu_sessions_for_ue(session)
            correlate_pfcp_to_pdu(records, session.pdu_sessions, warnings=warnings)
            session.pdu_session_count = len(session.pdu_sessions)

        diagnoses = self._diagnose_sessions(records, sessions, warnings=warnings, llm_provider=llm_provider)
        overall = _compute_overall_verdict(diagnoses)

        return AnalysisResult(
            path=records.path,
            file_name=records.file_name,
            profile_name=self.name,
            scope_count=len(sessions),
            overall_verdict=overall[0],
            overall_failure_point=overall[1],
            overall_root_cause=overall[2],
            overall_confidence=overall[3],
            warnings=warnings,
            scopes=[_scope_from_ue_session(session) for session in sessions],
            diagnoses=[_scope_diagnosis_from_legacy(item) for item in diagnoses],
        )

    def _diagnose_sessions(
        self,
        records: ExtractedRecordSet,
        sessions: list[UESession],
        *,
        warnings: list[str],
        llm_provider=None,
    ) -> list[SessionDiagnosis]:
        if llm_provider is not None:
            warnings.append(f"diagnosis_engine: llm ({llm_provider.config.model})")
        else:
            warnings.append("diagnosis_engine: rule")

        diagnoses: list[SessionDiagnosis] = []
        for session in sessions:
            signals = collect_signals(session, records)
            if llm_provider is not None:
                diagnosis = llm_diagnose_session(session, signals, llm_provider)
            else:
                diagnosis = diagnose_session(session, signals)
            diagnoses.append(diagnosis)
        return diagnoses


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


def _compute_overall_verdict(
    diagnoses: list[SessionDiagnosis],
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
