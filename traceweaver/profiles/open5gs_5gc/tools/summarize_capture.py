"""
`summarize_capture`: capture-wide event inventory and integrity signals.

This is the FIRST tool the LLM is expected to call. It exists to prevent
the classic failure mode "I saw some success events, therefore the whole
capture is a success":

  - `event_inventory` tells the LLM **every** event type that occurred,
    including deregistrations, failures, and rejects it might otherwise
    miss by only looking at a single UE timeline.
  - `capture_signals` derives consistency checks (e.g. "PFCP session
    setup requests without matching responses") so the LLM has to
    acknowledge contradictions before issuing a success verdict.
  - `ue_overview` lists every `ran_ue_ngap_id` with a compact event
    sequence, so the LLM can spot retries (same endpoint, new id) and
    multi-UE interactions at a glance.

Cheap, no arguments, always safe. The enforced workflow in the system
prompt makes this the first call of every investigation.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from traceweaver.core.tools.base import Tool, ToolContext, ToolResult, ToolSpec


# Event names that must be recognised for the capture_signals booleans.
_REGISTRATION_EVENTS = {
    "REGISTRATION_REQUEST", "REGISTRATION_ACCEPT",
    "REGISTRATION_COMPLETE",
}
_REGISTRATION_REJECT_EVENTS = {"REGISTRATION_REJECT"}
_DEREGISTRATION_EVENTS = {
    "DEREGISTRATION_REQUEST_UE_ORIG", "DEREGISTRATION_ACCEPT_UE_ORIG",
    "DEREGISTRATION_REQUEST_UE_TERM", "DEREGISTRATION_ACCEPT_UE_TERM",
}
_DEACTIVATION_EVENTS = {
    "DEACTIVATION_REQUEST", "DEACTIVATION_RESPONSE", "DEACTIVATION_COMPLETE",
}
_AUTH_FAILURE_EVENTS = {"AUTHENTICATION_FAILURE", "AUTHENTICATION_REJECT"}
_SERVICE_REJECT_EVENTS = {"SERVICE_REJECT"}
_UE_RELEASE_EVENTS = {"NGAP_UE_CONTEXT_RELEASE"}
_PDU_SETUP_REQUEST_EVENTS = {"PDU_SESSION_ESTABLISHMENT_REQUEST"}
_PDU_SETUP_COMPLETE_EVENTS = {
    "PDU_SESSION_ESTABLISHMENT_ACCEPT",
    "NGAP_PDU_SESSION_RESOURCE_SETUP",
}
_PDU_REJECT_EVENTS = {"PDU_SESSION_ESTABLISHMENT_REJECT"}

# PFCP message names (see PFCP_MSG_MAP in fields.py) that represent session setup.
_PFCP_SETUP_REQUEST_NAMES = {"SESSION_ESTABLISHMENT_REQUEST"}
_PFCP_SETUP_RESPONSE_NAMES = {"SESSION_ESTABLISHMENT_RESPONSE"}
_REGISTRATION_SUCCESS_HINT_EVENTS = {
    "REGISTRATION_ACCEPT",
    "REGISTRATION_COMPLETE",
    "AUTHENTICATION_RESPONSE",
    "SECURITY_MODE_COMMAND",
    "SECURITY_MODE_COMPLETE",
    "NGAP_INITIAL_CONTEXT_SETUP",
    "NGAP_DOWNLINK_NAS_TRANSPORT",
}
_PFCP_DELETE_REQUEST_NAMES = {"SESSION_DELETION_REQUEST"}
_PFCP_DELETE_RESPONSE_NAMES = {"SESSION_DELETION_RESPONSE"}

# Max events to list per UE in the overview (avoid prompt bloat).
_MAX_UE_EVENTS = 20


class SummarizeCaptureTool(Tool):
    spec = ToolSpec(
        name="summarize_capture",
        description=(
            "Return a capture-wide inventory of events, protocol "
            "distribution, per-UE event sequences, and consistency "
            "signals (e.g. whether PFCP setup requests got matching "
            "responses, whether deregistration is present, whether "
            "multiple RAN_UE_NGAP_IDs appear which may indicate a retry). "
            "CALL THIS FIRST on every investigation so you know what "
            "events exist in the whole capture before zooming in on a "
            "single UE. No arguments."
        ),
        parameters_schema={"type": "object", "properties": {}, "required": []},
    )

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        if ctx.source_handle is None:
            return ToolResult(
                data={
                    "total_records": 0,
                    "hint": "no source_handle",
                },
            )

        total = 0
        first_ts: float | None = None
        last_ts: float | None = None
        event_counts: Counter[str] = Counter()
        protocol_counts: Counter[str] = Counter()
        pfcp_name_counts: Counter[str] = Counter()
        http_status_counts: Counter[str] = Counter()
        sbi_calls: dict[tuple[str, str], dict[str, Any]] = {}
        # Per-UE view keyed by ran_ue_ngap_id
        ue_events: dict[str, list[str]] = {}
        ue_first_seq: dict[str, int] = {}
        ue_last_seq: dict[str, int] = {}

        for rec in ctx.source_handle.iter_records():
            total += 1
            ts = rec.timestamp
            if ts is not None:
                if first_ts is None or ts < first_ts:
                    first_ts = ts
                if last_ts is None or ts > last_ts:
                    last_ts = ts

            f = rec.fields
            ev = f.get("event")
            if ev:
                event_counts[str(ev)] += 1

            layer = f.get("protocol_layer")
            if layer:
                protocol_counts[str(layer)] += 1

            pfcp_name = f.get("pfcp_msg_name")
            if pfcp_name:
                pfcp_name_counts[str(pfcp_name)] += 1

            status = f.get("http2.headers.status")
            if status:
                http_status_counts[str(status)] += 1

            stream_id = f.get("http2.streamid")
            if stream_id:
                tcp_stream = f.get("tcp.stream") or ""
                sbi_key = (str(tcp_stream), str(stream_id))
                slot = sbi_calls.setdefault(
                    sbi_key,
                    {
                        "method": None,
                        "path": None,
                        "status": None,
                    },
                )
                method = f.get("http2.headers.method")
                path = f.get("http2.headers.path")
                if method and not slot["method"]:
                    slot["method"] = str(method)
                if path and not slot["path"]:
                    slot["path"] = str(path)
                if status and slot["status"] is None:
                    slot["status"] = str(status)

            ran = f.get("ran_ue_ngap_id")
            if ran is not None and ev:
                key = str(ran)
                evs = ue_events.setdefault(key, [])
                if len(evs) < _MAX_UE_EVENTS:
                    evs.append(str(ev))
                ue_first_seq.setdefault(key, rec.seq)
                ue_last_seq[key] = rec.seq

        time_span_s = (
            round(last_ts - first_ts, 3)
            if (first_ts is not None and last_ts is not None)
            else None
        )

        # Build ue_overview sorted by first_seq (temporal order)
        ue_overview = [
            {
                "ran_ue_ngap_id": key,
                "first_seq": ue_first_seq[key],
                "last_seq": ue_last_seq[key],
                "event_count": len(ue_events[key]),
                "events": ue_events[key],
            }
            for key in sorted(ue_events, key=lambda k: ue_first_seq[k])
        ]

        # Derive capture-wide signals the LLM MUST reconcile
        ev_set = set(event_counts)
        pfcp_set = set(pfcp_name_counts)

        pfcp_setup_reqs = sum(pfcp_name_counts[n] for n in _PFCP_SETUP_REQUEST_NAMES)
        pfcp_setup_resps = sum(pfcp_name_counts[n] for n in _PFCP_SETUP_RESPONSE_NAMES)
        pfcp_delete_reqs = sum(pfcp_name_counts[n] for n in _PFCP_DELETE_REQUEST_NAMES)
        pfcp_delete_resps = sum(pfcp_name_counts[n] for n in _PFCP_DELETE_RESPONSE_NAMES)

        has_http_5xx = any(s.startswith("5") for s in http_status_counts)
        has_http_4xx = any(s.startswith("4") for s in http_status_counts)

        sbi_missing_response_count = 0
        nausf_auth_missing_response_count = 0
        nsmf_pdu_http_4xx_count = 0
        nudm_sm_data_http_4xx_count = 0
        for call in sbi_calls.values():
            path = str(call.get("path") or "")
            status_text = str(call.get("status") or "")
            if call.get("method") and not call.get("status"):
                sbi_missing_response_count += 1
                if "/nausf-auth/" in path:
                    nausf_auth_missing_response_count += 1
            if status_text.startswith("4") and "/nsmf-pdusession/" in path:
                nsmf_pdu_http_4xx_count += 1
            if status_text.startswith("4") and "/sm-data" in path:
                nudm_sm_data_http_4xx_count += 1

        pdu_setup_started = any(n in ev_set for n in _PDU_SETUP_REQUEST_EVENTS)
        pdu_setup_completed = any(n in ev_set for n in _PDU_SETUP_COMPLETE_EVENTS)
        pdu_rejected = any(n in ev_set for n in _PDU_REJECT_EVENTS)

        has_deactivation = bool(ev_set & _DEACTIVATION_EVENTS)
        has_deregistration = bool(ev_set & _DEREGISTRATION_EVENTS)
        has_ue_context_release = bool(ev_set & _UE_RELEASE_EVENTS)
        has_failure_symptom = bool(
            (ev_set & _REGISTRATION_REJECT_EVENTS)
            or (ev_set & _AUTH_FAILURE_EVENTS)
            or (ev_set & _SERVICE_REJECT_EVENTS)
            or pdu_rejected
        )

        retry_pattern_present = False
        if len(ue_overview) > 1:
            saw_early_failure = False
            saw_later_fresh_start = False
            saw_later_success = False
            for idx, ue in enumerate(ue_overview):
                events = set(ue["events"])
                if events & (_AUTH_FAILURE_EVENTS | _REGISTRATION_REJECT_EVENTS):
                    saw_early_failure = True
                if idx > 0 and "REGISTRATION_REQUEST" in events:
                    saw_later_fresh_start = True
                if idx > 0 and (events & _REGISTRATION_SUCCESS_HINT_EVENTS):
                    saw_later_success = True
            retry_pattern_present = (
                saw_early_failure and saw_later_fresh_start and saw_later_success
            )

        likely_deregistration_flow = (
            has_deregistration
            or has_deactivation
            or (
                pdu_setup_completed
                and has_ue_context_release
                and pfcp_delete_reqs > 0
                and pfcp_delete_reqs == pfcp_delete_resps
            )
        )
        likely_pdu_session_failure = (
            pdu_setup_started
            and not pdu_setup_completed
            and (
                pdu_rejected
                or event_counts.get("PDU_SESSION_ESTABLISHMENT_REQUEST", 0) > 1
                or nsmf_pdu_http_4xx_count > 0
                or nudm_sm_data_http_4xx_count > 0
            )
        )

        signals = {
            "has_registration": bool(ev_set & _REGISTRATION_EVENTS),
            "has_registration_reject": bool(ev_set & _REGISTRATION_REJECT_EVENTS),
            "has_deregistration": has_deregistration,
            "has_deactivation": has_deactivation,
            "has_deregistration_or_deactivation": (
                has_deregistration or has_deactivation
            ),
            "has_authentication_failure": bool(ev_set & _AUTH_FAILURE_EVENTS),
            "has_service_reject": bool(ev_set & _SERVICE_REJECT_EVENTS),
            "pdu_session_setup_started": pdu_setup_started,
            "pdu_session_setup_completed": pdu_setup_completed,
            "pdu_session_rejected": pdu_rejected,
            "nsmf_pdu_http_4xx_count": nsmf_pdu_http_4xx_count,
            "nudm_sm_data_http_4xx_count": nudm_sm_data_http_4xx_count,
            "pfcp_setup_request_count": pfcp_setup_reqs,
            "pfcp_setup_response_count": pfcp_setup_resps,
            "pfcp_delete_request_count": pfcp_delete_reqs,
            "pfcp_delete_response_count": pfcp_delete_resps,
            "pfcp_setup_unbalanced": (
                pfcp_setup_reqs > 0 and pfcp_setup_reqs != pfcp_setup_resps
            ),
            "sbi_missing_response_count": sbi_missing_response_count,
            "nausf_auth_missing_response_count": nausf_auth_missing_response_count,
            "has_sbi_http_failure": has_http_5xx or has_http_4xx,
            "has_sbi_http_5xx": has_http_5xx,
            "has_sbi_http_4xx": has_http_4xx,
            "has_ue_context_release": has_ue_context_release,
            "ran_ue_ngap_id_count": len(ue_overview),
            "multiple_ran_ue_ngap_ids": len(ue_overview) > 1,
            "retry_pattern_present": retry_pattern_present,
            "likely_deregistration_flow": likely_deregistration_flow,
            "likely_retry_then_success": retry_pattern_present,
            "likely_pdu_session_failure": likely_pdu_session_failure,
            "likely_pfcp_failure": (
                pfcp_setup_reqs > 0 and pfcp_setup_reqs != pfcp_setup_resps
            ),
            "likely_sbi_failure": (
                has_http_5xx
                or has_http_4xx
                or (
                    has_failure_symptom
                    and (
                        sbi_missing_response_count > 0
                        or nausf_auth_missing_response_count > 0
                    )
                )
            ),
        }

        verdict_guardrails: list[str] = []
        if signals["likely_pfcp_failure"]:
            verdict_guardrails.append(
                "PFCP session setup requests are not balanced by responses; "
                "do not issue a success verdict before checking get_pfcp_exchanges."
            )
        if signals["likely_sbi_failure"]:
            verdict_guardrails.append(
                "SBI failure signals are present (HTTP failure or request without response); "
                "inspect get_sbi_calls before finalizing any success verdict."
            )
        if pdu_setup_started:
            verdict_guardrails.append(
                "PDU session activity is present; inspect at least one UE/session path "
                "with list_ue_sessions before finalizing."
            )
        if signals["likely_pdu_session_failure"]:
            verdict_guardrails.append(
                "PDU session establishment started but did not complete; prioritize a "
                "PDU/session diagnosis over a generic AUSF/SBI failure summary, and cite "
                "a PDU_SESSION_* / 5GSM finding if available."
            )
        if signals["likely_deregistration_flow"]:
            verdict_guardrails.append(
                "Capture indicates deregistration or session teardown after success; "
                "a pure registration-success summary is incomplete. Prefer citing "
                "event='DEREGISTRATION_OR_SESSION_TEARDOWN' in evidence if no more explicit "
                "DEREGISTRATION_* or DEACTIVATION_* event is available."
            )
        if signals["retry_pattern_present"]:
            verdict_guardrails.append(
                "Multiple RAN_UE_NGAP_IDs plus early failure and later success "
                "suggest a retry; do not stop at the first failed attempt."
            )

        capture_findings: list[dict[str, Any]] = []
        if signals["likely_pfcp_failure"]:
            capture_findings.append(
                {
                    "event": "PFCP_FAILURE_HINT",
                    "note": "PFCP session establishment requests are not matched by responses.",
                }
            )
        if likely_pdu_session_failure:
            capture_findings.append(
                {
                    "event": "PDU_SESSION_ESTABLISHMENT_REJECT_HINT",
                    "note": "PDU session establishment was attempted repeatedly but never completed; check Nsmf/Nudm 4xx responses and 5GSM context.",
                }
            )
        if signals["likely_sbi_failure"] and nausf_auth_missing_response_count > 0:
            capture_findings.append(
                {
                    "event": "SBI_AUSF_CALL_WITHOUT_RESPONSE",
                    "note": "Observed Nausf authentication request without a matching HTTP response.",
                }
            )
        elif signals["likely_sbi_failure"] and sbi_missing_response_count > 0:
            capture_findings.append(
                {
                    "event": "SBI_CALL_WITHOUT_RESPONSE",
                    "note": "Observed SBI request(s) without matching HTTP response headers.",
                }
            )
        if likely_deregistration_flow:
            capture_findings.append(
                {
                    "event": "DEREGISTRATION_OR_SESSION_TEARDOWN",
                    "note": "Observed teardown pattern: prior success followed by PFCP deletion and/or UE context release.",
                }
            )
        if retry_pattern_present:
            capture_findings.append(
                {
                    "event": "RETRY_THEN_SUCCESS",
                    "note": "An earlier UE attempt failed, and a later fresh RAN_UE_NGAP_ID progressed successfully.",
                }
            )

        data: dict[str, Any] = {
            "total_records": total,
            "time_span_s": time_span_s,
            "protocol_distribution": dict(protocol_counts),
            "event_inventory": dict(event_counts),
            "pfcp_message_inventory": dict(pfcp_name_counts) if pfcp_name_counts else None,
            "http_status_inventory": dict(http_status_counts) if http_status_counts else None,
            "ue_overview": ue_overview,
            "capture_signals": signals,
            "verdict_guardrails": verdict_guardrails,
            "capture_findings": capture_findings,
            "_interpretation_hint": (
                "Reconcile your verdict with capture_signals before "
                "finalizing. Examples of contradictions you MUST "
                "investigate: (a) verdict=success but has_deregistration_or_deactivation "
                "is true; "
                "(b) verdict=success but pfcp_setup_unbalanced is true; "
                "(c) verdict=success but likely_sbi_failure is true; "
                "(d) two verdicts for two ran_ue_ngap_ids when they may "
                "actually be the same UE retrying — check if one ends in "
                "failure and the other starts fresh with REGISTRATION_REQUEST."
            ),
        }

        if total == 0:
            data["hint"] = "capture is empty; no records ingested"

        return ToolResult(data=data)


__all__ = ["SummarizeCaptureTool"]
