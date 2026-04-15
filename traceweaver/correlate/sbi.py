from __future__ import annotations

import re
from collections import defaultdict

from traceweaver.models import ExtractedRecordSet, SBICall, UESession
from traceweaver.utils import parse_optional_int

DIRECT_IDENTITY_SERVICES = {"nudm-ueau", "nudm-uecm", "nudm-sdm", "namf-comm"}
TIME_WINDOW_SECONDS = 2.0


def _first_non_empty(*values: str | None) -> str | None:
    for value in values:
        normalized = (value or "").strip()
        if normalized:
            return normalized
    return None


def extract_identity_from_path(path: str | None) -> str | None:
    raw_path = (path or "").strip()
    if not raw_path:
        return None

    suci_match = re.search(r"(suci-[A-Za-z0-9-]+)", raw_path)
    if suci_match:
        return suci_match.group(1)

    imsi_match = re.search(r"(imsi-\d+)", raw_path)
    if imsi_match:
        return imsi_match.group(1)

    return None


def extract_sbi_service(path: str | None) -> str:
    raw_path = (path or "").strip()
    if not raw_path.startswith("/"):
        return "unknown"
    parts = raw_path.split("/")
    return parts[1] if len(parts) > 1 and parts[1] else "unknown"


def _connection_key(record) -> str:
    tcp_stream = parse_optional_int(record.fields.get("tcp.stream"))
    if tcp_stream is not None:
        return f"tcp-stream:{tcp_stream}"
    src = f"{record.src_ip}:{record.src_port}" if record.src_ip and record.src_port is not None else (record.src_ip or "")
    dst = f"{record.dst_ip}:{record.dst_port}" if record.dst_ip and record.dst_port is not None else (record.dst_ip or "")
    endpoints = sorted([src, dst])
    return "|".join(endpoints)


def pair_sbi_calls(record_set: ExtractedRecordSet) -> list[SBICall]:
    grouped: dict[tuple[str, int], list] = defaultdict(list)
    for record in record_set.records:
        if record.primary_protocol != "http2":
            continue
        stream_id = parse_optional_int(record.fields.get("http2.streamid"))
        if stream_id is None:
            continue
        path = _first_non_empty(record.fields.get("http2.headers.path"))
        status = parse_optional_int(record.fields.get("http2.headers.status"))
        method = _first_non_empty(record.fields.get("http2.headers.method"))
        if not any([path, status is not None, method]):
            continue
        grouped[(_connection_key(record), stream_id)].append(record)

    calls: list[SBICall] = []
    for (connection_key, stream_id), records in sorted(grouped.items(), key=lambda item: (item[0][0], item[0][1])):
        request_record = next(
            (record for record in records if _first_non_empty(record.fields.get("http2.headers.method"), record.fields.get("http2.headers.path"))),
            None,
        )
        response_record = next(
            (record for record in records if parse_optional_int(record.fields.get("http2.headers.status")) is not None),
            None,
        )
        seed_record = request_record or response_record or records[0]
        path = _first_non_empty(*(record.fields.get("http2.headers.path") for record in records))
        method = _first_non_empty(*(record.fields.get("http2.headers.method") for record in records))
        status = next(
            (
                parsed
                for parsed in (parse_optional_int(record.fields.get("http2.headers.status")) for record in records)
                if parsed is not None
            ),
            None,
        )
        call = SBICall(
            connection_key=connection_key,
            tcp_stream=parse_optional_int(seed_record.fields.get("tcp.stream")),
            stream_id=stream_id,
            service=extract_sbi_service(path),
            method=method,
            path=path,
            status=status,
            request_frame=request_record.frame_number if request_record else None,
            response_frame=response_record.frame_number if response_record else None,
            request_time_epoch=request_record.time_epoch if request_record else seed_record.time_epoch,
            response_time_epoch=response_record.time_epoch if response_record else None,
            src_ip=request_record.src_ip if request_record else seed_record.src_ip,
            dst_ip=request_record.dst_ip if request_record else seed_record.dst_ip,
            identity=extract_identity_from_path(path),
        )
        calls.append(call)
    return calls


def correlate_sbi_to_sessions(
    calls: list[SBICall],
    sessions: list[UESession],
    *,
    warnings: list[str] | None = None,
) -> list[SBICall]:
    identity_index: dict[str, UESession] = {}
    for session in sessions:
        if session.suci:
            identity_index[session.suci] = session
        if session.supi:
            identity_index[session.supi] = session

    unmatched_count = 0
    ambiguous_count = 0

    for call in calls:
        attached_session: UESession | None = None
        if call.identity and call.identity in identity_index:
            attached_session = identity_index[call.identity]
            call.match_confidence = "high"
            call.match_reason = "identity_path"
        else:
            timestamp = call.request_time_epoch or call.response_time_epoch
            candidates = [
                session
                for session in sessions
                if timestamp is not None
                and session.start_time_epoch is not None
                and session.end_time_epoch is not None
                and session.start_time_epoch <= timestamp <= session.end_time_epoch + TIME_WINDOW_SECONDS
            ]
            if len(candidates) == 1:
                attached_session = candidates[0]
                call.match_confidence = "medium"
                call.match_reason = "single_time_window_candidate"
            elif len(candidates) > 1:
                ambiguous_count += 1
                call.match_reason = "multiple_time_window_candidates"

        if attached_session is None:
            unmatched_count += 1
            continue

        if call.identity:
            if call.identity.startswith("suci-") and not attached_session.suci:
                attached_session.suci = call.identity
            if call.identity.startswith("imsi-") and not attached_session.supi:
                attached_session.supi = call.identity
            if attached_session.suci:
                identity_index[attached_session.suci] = attached_session
            if attached_session.supi:
                identity_index[attached_session.supi] = attached_session

        call.matched_session_id = attached_session.session_id
        attached_session.sbi_calls.append(call)
        attached_session.sbi_call_count += 1

    if warnings is not None:
        warnings.append(
            f"sbi_correlation_summary: total={len(calls)} matched={len(calls) - unmatched_count} "
            f"unmatched={unmatched_count} ambiguous={ambiguous_count}"
        )
        if unmatched_count > 0:
            warnings.append("sbi_correlation_unmatched_calls_detected")
        if ambiguous_count > 0:
            warnings.append("sbi_correlation_ambiguous_calls_detected")

    return calls
