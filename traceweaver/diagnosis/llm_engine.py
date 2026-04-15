from __future__ import annotations

import logging

from traceweaver.diagnosis.engine import diagnose_session as rule_diagnose_session
from traceweaver.llm.output import LLMDiagnosisOutput, parse_llm_diagnosis
from traceweaver.llm.prompts import build_diagnosis_prompt
from traceweaver.llm.provider import LLMProvider
from traceweaver.models import DiagnosticSignal, SessionDiagnosis, UESession

logger = logging.getLogger(__name__)


def llm_diagnose_session(
    session: UESession,
    signals: list[DiagnosticSignal],
    provider: LLMProvider,
) -> SessionDiagnosis:
    signal_names = sorted({s.name for s in signals})
    sbi_paths = sorted({
        str(s.details.get("path"))
        for s in signals
        if s.name == "SBI_HTTP2_REQUEST" and s.details.get("path")
    })

    tier = provider.config.model_tier
    system_prompt, user_prompt = build_diagnosis_prompt(session, signals, tier)

    max_attempts = provider.config.max_retries + 1
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            raw_json = provider.complete_json(system_prompt, user_prompt)
            result = parse_llm_diagnosis(raw_json)
            return _build_diagnosis(
                session, signals, signal_names, sbi_paths, result,
                source="llm", model=provider.config.model,
            )
        except Exception as exc:
            last_error = exc
            logger.warning(
                "LLM diagnosis attempt %d/%d failed: %s",
                attempt, max_attempts, exc,
            )

    logger.error(
        "All %d LLM diagnosis attempts failed for session %s, falling back to rule engine. Last error: %s",
        max_attempts, session.session_id, last_error,
    )
    fallback = rule_diagnose_session(session, signals)
    fallback.notes.append(f"llm_fallback: rule engine used after {max_attempts} LLM attempts failed")
    return fallback


def _build_diagnosis(
    session: UESession,
    signals: list[DiagnosticSignal],
    signal_names: list[str],
    sbi_paths: list[str],
    llm_output: LLMDiagnosisOutput,
    *,
    source: str,
    model: str,
) -> SessionDiagnosis:
    notes: list[str] = []
    notes.append(f"diagnosed_by: {source} ({model})")
    if llm_output.reasoning:
        notes.append(f"reasoning: {llm_output.reasoning}")
    notes.extend(f"suggestion: {s}" for s in llm_output.suggestions)
    notes.extend(f"limitation: {l}" for l in llm_output.limitations)
    notes.extend(
        f"evidence: frame {e.frame_number} — {e.description}"
        for e in llm_output.evidence
        if e.frame_number is not None
    )

    return SessionDiagnosis(
        session_id=session.session_id,
        verdict=llm_output.verdict,
        failure_point=llm_output.failure_point,
        root_cause=llm_output.root_cause,
        confidence=llm_output.confidence,
        signals=signals,
        signal_names=signal_names,
        sbi_paths=sbi_paths,
        notes=notes,
    )
