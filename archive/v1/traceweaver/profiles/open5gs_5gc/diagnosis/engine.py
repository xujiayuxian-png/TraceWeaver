from __future__ import annotations

from traceweaver.profiles.open5gs_5gc.domain.diagnosis import DiagnosticSignal, SessionDiagnosis
from traceweaver.profiles.open5gs_5gc.domain.sessions import UESession


def diagnose_session(session: UESession, signals: list[DiagnosticSignal]) -> SessionDiagnosis:
    signal_names = sorted({s.name for s in signals})
    sbi_paths = sorted({
        str(s.details.get("path"))
        for s in signals
        if s.name == "SBI_HTTP2_REQUEST" and s.details.get("path")
    })
    sn = set(signal_names)

    verdict, failure_point, root_cause, confidence, notes = _evaluate(sn, signals, sbi_paths, session)

    return SessionDiagnosis(
        session_id=session.session_id,
        verdict=verdict,
        failure_point=failure_point,
        root_cause=root_cause,
        confidence=confidence,
        signals=signals,
        signal_names=signal_names,
        sbi_paths=sbi_paths,
        notes=notes,
    )


def _evaluate(
    sn: set[str],
    signals: list[DiagnosticSignal],
    sbi_paths: list[str],
    session: UESession,
) -> tuple[str, str | None, str | None, str, list[str]]:
    notes: list[str] = []

    has_reg_req = "REGISTRATION_REQUEST" in sn
    has_reg_accept = "REGISTRATION_ACCEPT" in sn
    has_reg_reject = "REGISTRATION_REJECT" in sn
    has_auth_failure = "AUTHENTICATION_FAILURE" in sn
    has_auth_reject = "AUTHENTICATION_REJECT" in sn
    has_sec_cmd = "SECURITY_MODE_COMMAND" in sn
    has_sec_reject = "SECURITY_MODE_REJECT" in sn
    has_dereg_req = "DEREGISTRATION_REQUEST_UE_ORIG" in sn
    has_dereg_accept = "DEREGISTRATION_ACCEPT_UE_ORIG" in sn
    has_pdu_est_req = "PDU_SESSION_ESTABLISHMENT_REQUEST" in sn
    has_pdu_est_accept = "PDU_SESSION_ESTABLISHMENT_ACCEPT" in sn
    has_pdu_est_reject = "PDU_SESSION_ESTABLISHMENT_REJECT" in sn
    has_pdu_rel_req = "PDU_SESSION_RELEASE_REQUEST" in sn
    has_pdu_rel_cmd = "PDU_SESSION_RELEASE_COMMAND" in sn
    has_pdu_res_setup = "NGAP_PDU_SESSION_RESOURCE_SETUP" in sn
    has_t3580 = "T3580_RETRY" in sn
    has_retry_reg = "RETRY_REGISTRATION_REQUEST" in sn
    has_sbi_5xx = "SBI_5XX" in sn
    has_sbi_req = "SBI_HTTP2_REQUEST" in sn
    has_initial_ctx_setup = "NGAP_INITIAL_CONTEXT_SETUP" in sn

    reg_success_inferred = has_reg_accept or (
        has_sec_cmd and has_initial_ctx_setup and not has_reg_reject
    )
    pdu_success_inferred = has_pdu_est_accept or has_pdu_res_setup

    if has_retry_reg and reg_success_inferred:
        if has_auth_failure or has_auth_reject:
            return (
                "FAIL_THEN_OK",
                "AUTHENTICATION_ON_FIRST_ATTEMPT",
                "first_attempt_bad_key_then_retry_with_good_key",
                "high",
                notes,
            )
        return (
            "FAIL_THEN_OK",
            "REGISTRATION_ON_FIRST_ATTEMPT",
            "registration_retry_succeeded",
            "medium",
            notes,
        )

    if has_auth_failure and not reg_success_inferred:
        return (
            "FAIL",
            "AUTHENTICATION",
            "aka_mac_mismatch_or_bad_subscription_key",
            "high",
            notes,
        )

    if has_reg_reject and has_sbi_5xx:
        return (
            "FAIL",
            "AUTHENTICATION_OR_REGISTRATION_DOWNSTREAM_SBI",
            "udm_unavailable_causing_ausf_auth_chain_failure",
            "high",
            notes,
        )

    if has_reg_reject and has_sbi_req:
        sbi_4xx_auth = any(
            s.name == "SBI_4XX"
            and s.details.get("service") in ("nausf-auth", "nudm-ueau", "nudr-dr")
            and s.details.get("status") == 404
            for s in signals
        )
        if sbi_4xx_auth:
            return (
                "FAIL",
                "REGISTRATION",
                "unknown_or_unprovisioned_subscriber",
                "high",
                notes,
            )

        auth_paths = [p for p in sbi_paths if "nausf-auth" in p or "nudm" in p]
        if auth_paths:
            return (
                "FAIL",
                "AUTHENTICATION_OR_REGISTRATION_DOWNSTREAM_SBI",
                "udm_unavailable_causing_ausf_auth_chain_failure",
                "high",
                notes,
            )
        return (
            "FAIL",
            "REGISTRATION",
            "sbi_downstream_failure",
            "medium",
            notes,
        )

    if has_reg_reject and not reg_success_inferred:
        return (
            "FAIL",
            "REGISTRATION",
            "unknown_or_unprovisioned_subscriber",
            "high",
            notes,
        )

    if has_sec_reject and not reg_success_inferred:
        return (
            "FAIL",
            "REGISTRATION",
            "ue_security_capabilities_mismatch",
            "medium",
            notes,
        )

    if has_t3580 and not pdu_success_inferred:
        return (
            "FAIL",
            "PDU_SESSION_ESTABLISHMENT",
            "upf_or_pfcp_downstream_unavailable",
            "high",
            notes,
        )

    if has_pdu_est_reject and not pdu_success_inferred:
        return (
            "FAIL",
            "PDU_SESSION_ESTABLISHMENT",
            "sm_forwarding_failure_or_payload_not_forwarded",
            "medium",
            notes,
        )

    if has_pdu_est_req and not pdu_success_inferred and not has_pdu_est_reject:
        gsm_status = "5GSM_STATUS" in sn
        if gsm_status:
            return (
                "FAIL",
                "PDU_SESSION_ESTABLISHMENT",
                "sm_forwarding_failure_or_payload_not_forwarded",
                "medium",
                notes,
            )

    if _is_truncated(sn, has_reg_req, reg_success_inferred, session):
        notes.append("capture appears truncated or incomplete")
        return (
            "INCONCLUSIVE",
            "UNKNOWN_DUE_TO_TRUNCATION",
            "capture_stopped_early",
            "high",
            notes,
        )

    partial_no_pfcp = "PARTIAL_CAPTURE_NO_PFCP" in sn

    if has_dereg_req and has_dereg_accept:
        return ("OK", None, None, "medium", notes)

    if has_pdu_rel_req and has_pdu_rel_cmd:
        return ("OK", None, None, "high", notes)

    if partial_no_pfcp and pdu_success_inferred:
        notes.append("PFCP not visible in capture; PFCP-related conclusions are incomplete")
        return (
            "INCONCLUSIVE",
            None,
            "capture_scope_is_intentionally_partial",
            "high",
            notes,
        )

    if reg_success_inferred and pdu_success_inferred:
        return ("OK", None, None, "high", notes)

    if reg_success_inferred:
        return ("OK", None, None, "high", notes)

    if not has_reg_req and not session.events:
        notes.append("no NAS events detected in this session")
        return ("INCONCLUSIVE", None, None, "low", notes)

    return ("INCONCLUSIVE", None, None, "low", notes)


def _is_truncated(
    sn: set[str],
    has_reg_req: bool,
    reg_success: bool,
    session: UESession,
) -> bool:
    if has_reg_req and not reg_success and "REGISTRATION_REJECT" not in sn:
        has_auth = "AUTHENTICATION_REQUEST" in sn or "AUTHENTICATION_RESPONSE" in sn
        if not has_auth:
            return True
    event_count = len(session.events)
    if event_count > 0 and event_count <= 2 and has_reg_req and not reg_success:
        return True
    return False
