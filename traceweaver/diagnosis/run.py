from __future__ import annotations

from pathlib import Path
from typing import Sequence

from traceweaver.correlate.pdu import build_pdu_sessions_for_ue, correlate_pfcp_to_pdu
from traceweaver.correlate.sbi import correlate_sbi_to_sessions, pair_sbi_calls
from traceweaver.correlate.ue_sessions import group_ue_sessions
from traceweaver.diagnosis.engine import diagnose_session
from traceweaver.diagnosis.signals import collect_signals
from traceweaver.ingest.records import extract_5gc_records
from traceweaver.models import DiagnosisReport


def run_diagnosis(
    path: str | Path,
    *,
    display_filter: str | None = None,
    decode_as: Sequence[str] | None = None,
    limit: int | None = None,
    llm_provider=None,
) -> DiagnosisReport:
    records = extract_5gc_records(
        path,
        display_filter=display_filter,
        decode_as=decode_as,
        limit=limit,
    )
    warnings = list(records.warnings)
    sessions = group_ue_sessions(records, warnings=warnings)
    correlate_sbi_to_sessions(pair_sbi_calls(records), sessions, warnings=warnings)

    for session in sessions:
        session.pdu_sessions = build_pdu_sessions_for_ue(session)
        correlate_pfcp_to_pdu(records, session.pdu_sessions, warnings=warnings)
        session.pdu_session_count = len(session.pdu_sessions)

    if llm_provider is not None:
        from traceweaver.diagnosis.llm_engine import llm_diagnose_session
        diagnose_fn = lambda sess, sigs: llm_diagnose_session(sess, sigs, llm_provider)
        warnings.append(f"diagnosis_engine: llm ({llm_provider.config.model})")
    else:
        diagnose_fn = diagnose_session
        warnings.append("diagnosis_engine: rule")

    diagnoses = []
    for session in sessions:
        signals = collect_signals(session, records)
        diagnosis = diagnose_fn(session, signals)
        diagnoses.append(diagnosis)

    overall = _compute_overall_verdict(diagnoses)

    return DiagnosisReport(
        path=records.path,
        file_name=records.file_name,
        session_count=len(sessions),
        overall_verdict=overall[0],
        overall_failure_point=overall[1],
        overall_root_cause=overall[2],
        overall_confidence=overall[3],
        warnings=warnings,
        sessions=diagnoses,
    )


def _compute_overall_verdict(
    diagnoses: list,
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
