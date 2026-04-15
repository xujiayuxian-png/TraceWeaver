from __future__ import annotations

from traceweaver.models import DetectedEvent, ExtractedRecordSet, NormalizedRecord

NAS_MM_EVENT_MAP = {
    65: "REGISTRATION_REQUEST",
    66: "REGISTRATION_ACCEPT",
    67: "REGISTRATION_COMPLETE",
    68: "REGISTRATION_REJECT",
    69: "DEREGISTRATION_REQUEST_UE_ORIG",
    70: "DEREGISTRATION_ACCEPT_UE_ORIG",
    71: "DEREGISTRATION_REQUEST_UE_TERM",
    72: "DEREGISTRATION_ACCEPT_UE_TERM",
    76: "SERVICE_REJECT",
    86: "AUTHENTICATION_REQUEST",
    87: "AUTHENTICATION_RESPONSE",
    88: "AUTHENTICATION_RESULT",
    89: "AUTHENTICATION_FAILURE",
    90: "AUTHENTICATION_REJECT",
    93: "SECURITY_MODE_COMMAND",
    94: "SECURITY_MODE_COMPLETE",
    95: "SECURITY_MODE_REJECT",
    100: "5GMM_STATUS",
}

NAS_SM_EVENT_MAP = {
    193: "PDU_SESSION_ESTABLISHMENT_REQUEST",
    194: "PDU_SESSION_ESTABLISHMENT_ACCEPT",
    195: "PDU_SESSION_ESTABLISHMENT_REJECT",
    196: "PDU_SESSION_AUTHENTICATION_COMMAND",
    201: "PDU_SESSION_MODIFICATION_REQUEST",
    202: "PDU_SESSION_MODIFICATION_ACCEPT",
    203: "PDU_SESSION_MODIFICATION_REJECT",
    209: "PDU_SESSION_RELEASE_REQUEST",
    210: "PDU_SESSION_RELEASE_REJECT",
    211: "PDU_SESSION_RELEASE_COMMAND",
    212: "PDU_SESSION_RELEASE_COMPLETE",
    214: "5GSM_STATUS",
}

NGAP_PROCEDURE_EVENT_MAP = {
    14: "NGAP_INITIAL_CONTEXT_SETUP",
    29: "NGAP_PDU_SESSION_RESOURCE_SETUP",
    30: "NGAP_PDU_SESSION_RESOURCE_RELEASE",
    41: "NGAP_UE_CONTEXT_RELEASE",
    46: "NGAP_DOWNLINK_NAS_TRANSPORT",
    47: "NGAP_UPLINK_NAS_TRANSPORT",
}


def _parse_int(raw_value: str) -> int | None:
    value = (raw_value or "").strip()
    if not value:
        return None
    try:
        return int(value, 0)
    except ValueError:
        return None


def detect_events_for_record(record: NormalizedRecord) -> list[DetectedEvent]:
    events: list[DetectedEvent] = []

    mm_type = _parse_int(record.fields.get("nas_5gs.mm.message_type", ""))
    if mm_type in NAS_MM_EVENT_MAP:
        events.append(
            DetectedEvent(
                frame_number=record.frame_number,
                time_epoch=record.time_epoch,
                protocol="nas_5gmm",
                event_name=NAS_MM_EVENT_MAP[mm_type],
                message_type=mm_type,
                cause=_parse_int(record.fields.get("nas_5gs.mm.5gmm_cause", "")),
                ran_ue_ngap_id=record.fields.get("ngap.RAN_UE_NGAP_ID") or None,
                amf_ue_ngap_id=record.fields.get("ngap.AMF_UE_NGAP_ID") or None,
                pdu_session_id=record.fields.get("nas_5gs.pdu_session_id") or None,
                src_ip=record.src_ip,
                dst_ip=record.dst_ip,
                fields=record.fields,
            )
        )

    sm_type = _parse_int(record.fields.get("nas_5gs.sm.message_type", ""))
    if sm_type in NAS_SM_EVENT_MAP:
        events.append(
            DetectedEvent(
                frame_number=record.frame_number,
                time_epoch=record.time_epoch,
                protocol="nas_5gsm",
                event_name=NAS_SM_EVENT_MAP[sm_type],
                message_type=sm_type,
                cause=_parse_int(record.fields.get("nas_5gs.sm.5gsm_cause", "")),
                ran_ue_ngap_id=record.fields.get("ngap.RAN_UE_NGAP_ID") or None,
                amf_ue_ngap_id=record.fields.get("ngap.AMF_UE_NGAP_ID") or None,
                pdu_session_id=(record.fields.get("nas_5gs.pdu_session_id") or record.fields.get("ngap.pDUSessionID")) or None,
                src_ip=record.src_ip,
                dst_ip=record.dst_ip,
                fields=record.fields,
            )
        )

    if record.primary_protocol == "ngap" and not events:
        proc_code = _parse_int(record.fields.get("ngap.procedureCode", ""))
        if proc_code in NGAP_PROCEDURE_EVENT_MAP:
            events.append(
                DetectedEvent(
                    frame_number=record.frame_number,
                    time_epoch=record.time_epoch,
                    protocol="ngap",
                    event_name=NGAP_PROCEDURE_EVENT_MAP[proc_code],
                    message_type=proc_code,
                    ran_ue_ngap_id=record.fields.get("ngap.RAN_UE_NGAP_ID") or None,
                    amf_ue_ngap_id=record.fields.get("ngap.AMF_UE_NGAP_ID") or None,
                    pdu_session_id=record.fields.get("ngap.pDUSessionID") or None,
                    src_ip=record.src_ip,
                    dst_ip=record.dst_ip,
                    fields=record.fields,
                )
            )

    return events


def detect_events(record_set: ExtractedRecordSet) -> list[DetectedEvent]:
    events: list[DetectedEvent] = []
    for record in record_set.records:
        events.extend(detect_events_for_record(record))
    return events
