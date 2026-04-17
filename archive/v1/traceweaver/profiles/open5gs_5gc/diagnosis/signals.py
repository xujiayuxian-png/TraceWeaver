from __future__ import annotations

from traceweaver.profiles.open5gs_5gc.domain.diagnosis import DiagnosticSignal
from traceweaver.profiles.open5gs_5gc.domain.records import ExtractedRecordSet
from traceweaver.profiles.open5gs_5gc.domain.sessions import UESession
from traceweaver.utils import parse_optional_int

PFCP_MSG_TYPE_NAMES: dict[int, str] = {
    1: "HEARTBEAT_REQUEST",
    2: "HEARTBEAT_RESPONSE",
    5: "ASSOCIATION_SETUP_REQUEST",
    6: "ASSOCIATION_SETUP_RESPONSE",
    50: "SESSION_ESTABLISHMENT_REQUEST",
    51: "SESSION_ESTABLISHMENT_RESPONSE",
    52: "SESSION_MODIFICATION_REQUEST",
    53: "SESSION_MODIFICATION_RESPONSE",
    54: "SESSION_DELETION_REQUEST",
    55: "SESSION_DELETION_RESPONSE",
}


def collect_signals(session: UESession, record_set: ExtractedRecordSet) -> list[DiagnosticSignal]:
    signals: list[DiagnosticSignal] = []
    signals.extend(_collect_nas_signals(session))
    signals.extend(_collect_sbi_signals(session))
    signals.extend(_collect_pfcp_signals(session))
    signals.extend(_collect_retry_signals(session))
    signals.extend(_collect_pfcp_record_signals(record_set, session))
    signals.extend(_collect_capture_visibility_signals(record_set))
    signals.sort(key=lambda s: (s.time_epoch or 0.0, s.name))
    return signals


def _collect_nas_signals(session: UESession) -> list[DiagnosticSignal]:
    signals: list[DiagnosticSignal] = []
    for event in session.events:
        signals.append(
            DiagnosticSignal(
                name=event.event_name,
                source="nas_event",
                frame_number=event.frame_number,
                time_epoch=event.time_epoch,
                details={
                    "protocol": event.protocol,
                    "message_type": event.message_type,
                    "cause": event.cause,
                },
            )
        )
    return signals


def _collect_sbi_signals(session: UESession) -> list[DiagnosticSignal]:
    signals: list[DiagnosticSignal] = []
    for call in session.sbi_calls:
        signals.append(
            DiagnosticSignal(
                name="SBI_HTTP2_REQUEST",
                source="sbi_call",
                frame_number=call.request_frame,
                time_epoch=call.request_time_epoch,
                details={
                    "service": call.service,
                    "method": call.method,
                    "path": call.path,
                    "status": call.status,
                },
            )
        )
        if call.status is not None and call.status >= 500:
            signals.append(
                DiagnosticSignal(
                    name="SBI_5XX",
                    source="sbi_call",
                    frame_number=call.response_frame,
                    time_epoch=call.response_time_epoch,
                    details={
                        "service": call.service,
                        "path": call.path,
                        "status": call.status,
                    },
                )
            )
        if call.status is not None and 400 <= call.status < 500:
            signals.append(
                DiagnosticSignal(
                    name="SBI_4XX",
                    source="sbi_call",
                    frame_number=call.response_frame,
                    time_epoch=call.response_time_epoch,
                    details={
                        "service": call.service,
                        "path": call.path,
                        "status": call.status,
                    },
                )
            )
    return signals


def _collect_pfcp_signals(session: UESession) -> list[DiagnosticSignal]:
    signals: list[DiagnosticSignal] = []
    for pdu_flow in session.pdu_sessions:
        for pfcp in pdu_flow.pfcp_flows:
            type_name = PFCP_MSG_TYPE_NAMES.get(pfcp.msg_type or -1)
            if type_name is None:
                type_name = f"PFCP_TYPE_{pfcp.msg_type}"

            signal_name = f"PFCP_{type_name}"
            signals.append(
                DiagnosticSignal(
                    name=signal_name,
                    source="pfcp_flow",
                    frame_number=pfcp.frame_number,
                    time_epoch=pfcp.time_epoch,
                    details={
                        "msg_type": pfcp.msg_type,
                        "seid": pfcp.seid,
                        "cause": pfcp.cause,
                    },
                )
            )
    return signals


def _collect_retry_signals(session: UESession) -> list[DiagnosticSignal]:
    signals: list[DiagnosticSignal] = []
    for pdu_flow in session.pdu_sessions:
        establishment_requests: list[tuple[int, float]] = []
        has_accept = False
        for event in pdu_flow.events:
            if event.event_name == "PDU_SESSION_ESTABLISHMENT_REQUEST":
                establishment_requests.append((event.frame_number, event.time_epoch))
            elif event.event_name == "PDU_SESSION_ESTABLISHMENT_ACCEPT":
                has_accept = True

        if len(establishment_requests) > 1 and not has_accept:
            signals.append(
                DiagnosticSignal(
                    name="T3580_RETRY",
                    source="retry_detection",
                    frame_number=establishment_requests[-1][0],
                    time_epoch=establishment_requests[-1][1],
                    details={
                        "attempt_count": len(establishment_requests),
                        "pdu_session_id": pdu_flow.pdu_session_id,
                    },
                )
            )

    reg_requests: list[tuple[int, float]] = []
    for event in session.events:
        if event.event_name == "REGISTRATION_REQUEST":
            reg_requests.append((event.frame_number, event.time_epoch))

    if len(reg_requests) > 1:
        signals.append(
            DiagnosticSignal(
                name="RETRY_REGISTRATION_REQUEST",
                source="retry_detection",
                frame_number=reg_requests[-1][0],
                time_epoch=reg_requests[-1][1],
                details={"attempt_count": len(reg_requests)},
            )
        )

    return signals


def _collect_pfcp_record_signals(
    record_set: ExtractedRecordSet, session: UESession
) -> list[DiagnosticSignal]:
    signals: list[DiagnosticSignal] = []
    assoc_requests: list[tuple[int, float]] = []

    for record in record_set.records:
        msg_type = parse_optional_int(record.fields.get("pfcp.msg_type"))
        if msg_type is None:
            continue

        if msg_type == 5:
            assoc_requests.append((record.frame_number, record.time_epoch))

        if msg_type == 6:
            cause = parse_optional_int(record.fields.get("pfcp.cause"))
            if cause is not None and cause != 1:
                signals.append(
                    DiagnosticSignal(
                        name="PFCP_ASSOCIATION_SETUP_FAILURE",
                        source="pfcp_record",
                        frame_number=record.frame_number,
                        time_epoch=record.time_epoch,
                        details={"cause": cause},
                    )
                )

    if len(assoc_requests) > 1:
        signals.append(
            DiagnosticSignal(
                name="PFCP_ASSOCIATION_RETRY",
                source="pfcp_record",
                frame_number=assoc_requests[-1][0],
                time_epoch=assoc_requests[-1][1],
                details={"attempt_count": len(assoc_requests)},
            )
        )

    return signals


def _collect_capture_visibility_signals(record_set: ExtractedRecordSet) -> list[DiagnosticSignal]:
    signals: list[DiagnosticSignal] = []
    seen_protocols: set[str] = set()
    for record in record_set.records:
        if record.primary_protocol:
            seen_protocols.add(record.primary_protocol)

    has_ngap = "ngap" in seen_protocols or "nas_5gs" in seen_protocols
    has_http2 = "http2" in seen_protocols
    has_pfcp = "pfcp" in seen_protocols

    if has_ngap:
        signals.append(DiagnosticSignal(name="NGAP_VISIBLE", source="capture_visibility"))
    if has_http2:
        signals.append(DiagnosticSignal(name="SBI_HTTP2_VISIBLE", source="capture_visibility"))
    if has_pfcp:
        signals.append(DiagnosticSignal(name="PFCP_VISIBLE", source="capture_visibility"))

    if has_ngap and not has_pfcp:
        signals.append(
            DiagnosticSignal(
                name="PARTIAL_CAPTURE_NO_PFCP",
                source="capture_visibility",
                details={"visible_protocols": ",".join(sorted(seen_protocols))},
            )
        )

    last_record = record_set.records[-1] if record_set.records else None
    if last_record and record_set.record_count < 20:
        signals.append(
            DiagnosticSignal(
                name="LOW_RECORD_COUNT",
                source="capture_visibility",
                details={"record_count": record_set.record_count},
            )
        )

    return signals
