"""
`get_ue_timeline`: all enriched events for a given UE, in order.

The LLM calls this once it has picked a UE from `list_ue_sessions` (or
inferred an id from user text). The output is compact: one dict per
frame that has an `event`, with just the fields a diagnosis needs.
"""

from __future__ import annotations

from typing import Any

from traceweaver.core.tools.base import Tool, ToolContext, ToolResult, ToolSpec


_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200
_SUCCESS_HINT_EVENTS = {
    "REGISTRATION_ACCEPT",
    "REGISTRATION_COMPLETE",
    "AUTHENTICATION_RESPONSE",
    "SECURITY_MODE_COMMAND",
    "SECURITY_MODE_COMPLETE",
    "NGAP_INITIAL_CONTEXT_SETUP",
    "NGAP_DOWNLINK_NAS_TRANSPORT",
    "PDU_SESSION_ESTABLISHMENT_ACCEPT",
    "NGAP_PDU_SESSION_RESOURCE_SETUP",
}
_EXPLICIT_DEREG_EVENTS = {
    "DEREGISTRATION_REQUEST_UE_ORIG",
    "DEREGISTRATION_ACCEPT_UE_ORIG",
    "DEREGISTRATION_REQUEST_UE_TERM",
    "DEREGISTRATION_ACCEPT_UE_TERM",
    "DEACTIVATION_REQUEST",
    "DEACTIVATION_RESPONSE",
    "DEACTIVATION_COMPLETE",
}
_PDU_SUCCESS_EVENTS = {
    "PDU_SESSION_ESTABLISHMENT_ACCEPT",
    "NGAP_PDU_SESSION_RESOURCE_SETUP",
}
_PDU_FAILURE_EVENTS = {
    "PDU_SESSION_ESTABLISHMENT_REJECT",
    "PDU_SESSION_ESTABLISHMENT_REJECT_HINT",
}


def _append_teardown_finding(events: list[dict[str, Any]], limit: int) -> None:
    event_names = {str(e.get("event") or "") for e in events}
    if event_names & _EXPLICIT_DEREG_EVENTS:
        return
    if "NGAP_UE_CONTEXT_RELEASE" not in event_names:
        return
    if not (event_names & _SUCCESS_HINT_EVENTS):
        return
    release_seq = None
    release_ts = None
    release_layer = None
    for ev in reversed(events):
        if ev.get("event") == "NGAP_UE_CONTEXT_RELEASE":
            release_seq = ev.get("seq")
            release_ts = ev.get("timestamp")
            release_layer = ev.get("protocol_layer")
            break
    if release_seq is None:
        return
    if len(events) >= limit:
        return
    events.append(
        {
            "seq": release_seq,
            "timestamp": release_ts,
            "event": "DEREGISTRATION_OR_SESSION_TEARDOWN",
            "protocol_layer": release_layer,
            "mm_cause": None,
            "sm_cause": None,
            "src_ip": None,
            "dst_ip": None,
            "pdu_session_id": None,
        }
    )


def _append_pdu_failure_finding(
    ctx: ToolContext,
    events: list[dict[str, Any]],
    limit: int,
) -> None:
    if ctx.source_handle is None or len(events) >= limit:
        return
    event_names = {str(e.get("event") or "") for e in events}
    if event_names & _PDU_FAILURE_EVENTS:
        return
    if event_names & _PDU_SUCCESS_EVENTS:
        return

    ue_ids: set[str] = set()
    pdu_request_count = 0
    last_pdu_request_seq = None
    last_pdu_request_ts = None
    nsmf_pdu_http_4xx_count = 0
    nudm_sm_data_http_4xx_count = 0

    for rec in ctx.source_handle.iter_records():
        f = rec.fields
        ran = f.get("ran_ue_ngap_id")
        if ran is not None and str(ran):
            ue_ids.add(str(ran))

        event = f.get("event")
        if event == "PDU_SESSION_ESTABLISHMENT_REQUEST":
            pdu_request_count += 1
            last_pdu_request_seq = rec.seq
            last_pdu_request_ts = rec.timestamp

        path = str(f.get("http2.headers.path") or "")
        status = str(f.get("http2.headers.status") or "")
        if status.startswith("4") and "/nsmf-pdusession/" in path:
            nsmf_pdu_http_4xx_count += 1
        if status.startswith("4") and "/sm-data" in path:
            nudm_sm_data_http_4xx_count += 1

    if len(ue_ids) > 1:
        return
    if pdu_request_count == 0:
        return
    if not (
        pdu_request_count > 1
        or nsmf_pdu_http_4xx_count > 0
        or nudm_sm_data_http_4xx_count > 0
    ):
        return
    if last_pdu_request_seq is None:
        return

    events.append(
        {
            "seq": last_pdu_request_seq,
            "timestamp": last_pdu_request_ts,
            "event": "PDU_SESSION_ESTABLISHMENT_REJECT_HINT",
            "protocol_layer": "nas_5gsm",
            "mm_cause": None,
            "sm_cause": None,
            "src_ip": None,
            "dst_ip": None,
            "pdu_session_id": None,
        }
    )


def _match(rec_fields: dict[str, Any], ran: str | None, amf: str | None) -> bool:
    if ran is not None:
        if str(rec_fields.get("ran_ue_ngap_id") or "") != ran:
            return False
    if amf is not None:
        if str(rec_fields.get("amf_ue_ngap_id") or "") != amf:
            return False
    return True


class GetUETimelineTool(Tool):
    spec = ToolSpec(
        name="get_ue_timeline",
        description=(
            "Return the ordered timeline of NAS/NGAP events for a specific "
            "UE. Provide at least one of `ran_ue_ngap_id` or "
            "`amf_ue_ngap_id` (use the string form returned by "
            "`list_ue_sessions`). Only frames that carry an `event` field "
            "are returned; each has `{seq, timestamp, event, "
            "protocol_layer, mm_cause, sm_cause, src_ip, dst_ip}`. "
            "For clean teardown after an otherwise successful session, the "
            "tool may append a derived terminal event "
            "`DEREGISTRATION_OR_SESSION_TEARDOWN` using the release seq. "
            "For single-UE captures where PDU session establishment keeps "
            "retrying without completion, the tool may append a derived "
            "terminal event `PDU_SESSION_ESTABLISHMENT_REJECT_HINT`. "
            "Use `limit` to cap output (default 50, max 200)."
        ),
        parameters_schema={
            "type": "object",
            "properties": {
                "ran_ue_ngap_id": {"type": "string"},
                "amf_ue_ngap_id": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": _MAX_LIMIT},
            },
            "required": [],
        },
    )

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        if ctx.source_handle is None:
            return ToolResult(
                data={"events": [], "count": 0, "hint": "no source_handle"},
            )

        ran = kwargs.get("ran_ue_ngap_id")
        amf = kwargs.get("amf_ue_ngap_id")
        if ran in (None, ""):
            ran = None
        else:
            ran = str(ran)
        if amf in (None, ""):
            amf = None
        else:
            amf = str(amf)
        if ran is None and amf is None:
            return ToolResult(
                data={
                    "events": [],
                    "count": 0,
                    "hint": (
                        "provide at least one of ran_ue_ngap_id / "
                        "amf_ue_ngap_id; call list_ue_sessions first to see "
                        "the valid values."
                    ),
                },
            )

        try:
            limit = int(kwargs.get("limit") or _DEFAULT_LIMIT)
        except (TypeError, ValueError):
            limit = _DEFAULT_LIMIT
        limit = max(1, min(limit, _MAX_LIMIT))

        events: list[dict[str, Any]] = []
        for rec in ctx.source_handle.iter_records():
            if rec.fields.get("event") is None:
                continue
            if not _match(rec.fields, ran, amf):
                continue
            events.append(
                {
                    "seq": rec.seq,
                    "timestamp": rec.timestamp,
                    "event": rec.fields.get("event"),
                    "protocol_layer": rec.fields.get("protocol_layer"),
                    "mm_cause": rec.fields.get("mm_cause"),
                    "sm_cause": rec.fields.get("sm_cause"),
                    "src_ip": rec.fields.get("src_ip"),
                    "dst_ip": rec.fields.get("dst_ip"),
                    "pdu_session_id": rec.fields.get("pdu_session_id"),
                }
            )
            if len(events) >= limit:
                break

        _append_teardown_finding(events, limit)
        _append_pdu_failure_finding(ctx, events, limit)

        data: dict[str, Any] = {
            "events": events,
            "count": len(events),
            "filter": {"ran_ue_ngap_id": ran, "amf_ue_ngap_id": amf},
        }
        if not events:
            data["hint"] = (
                "no events match. Confirm the UE id with list_ue_sessions "
                "(values are strings, and missing ids are returned as empty)."
            )
        return ToolResult(data=data)


__all__ = ["GetUETimelineTool"]
