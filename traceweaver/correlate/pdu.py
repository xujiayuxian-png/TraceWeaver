from __future__ import annotations

import re

from traceweaver.models import ExtractedRecordSet, PDUSessionFlow, PFCPFlow, SBICall, UESession
from traceweaver.utils import parse_optional_int

PDU_SBI_WINDOW_SECONDS = 2.0
PFCP_WINDOW_SECONDS = 5.0


def extract_pdu_session_id_from_sbi_path(path: str | None) -> str | None:
    raw = (path or "").strip()
    if not raw:
        return None
    match = re.search(r"imsi-[^/_]+_(\d+)(?:/|$)", raw)
    if match:
        return match.group(1)
    return None


def infer_smf_ips(session: UESession) -> set[str]:
    smf_ips: set[str] = set()
    for call in session.sbi_calls:
        if call.service == "nsmf-pdusession" and call.dst_ip:
            smf_ips.add(call.dst_ip)
    return smf_ips


def build_pdu_sessions_for_ue(session: UESession) -> list[PDUSessionFlow]:
    grouped: dict[str, PDUSessionFlow] = {}
    for event in session.events:
        if event.protocol != "nas_5gsm" or not event.pdu_session_id:
            continue
        pdu_id = event.pdu_session_id
        flow = grouped.get(pdu_id)
        if flow is None:
            flow = PDUSessionFlow(pdu_session_id=pdu_id, parent_session_id=session.session_id)
            grouped[pdu_id] = flow
        flow.events.append(event)
        flow.event_count += 1
        if flow.start_time_epoch is None or event.time_epoch < flow.start_time_epoch:
            flow.start_time_epoch = event.time_epoch
        if flow.end_time_epoch is None or event.time_epoch > flow.end_time_epoch:
            flow.end_time_epoch = event.time_epoch

    for call in session.sbi_calls:
        if call.service != "nsmf-pdusession":
            continue
        pdu_id = extract_pdu_session_id_from_sbi_path(call.path)
        target: PDUSessionFlow | None = None
        if pdu_id and pdu_id in grouped:
            target = grouped[pdu_id]
        elif len(grouped) == 1:
            target = next(iter(grouped.values()))
        else:
            timestamp = call.request_time_epoch or call.response_time_epoch
            if timestamp is not None:
                candidates = [
                    flow
                    for flow in grouped.values()
                    if flow.start_time_epoch is not None
                    and flow.start_time_epoch - PDU_SBI_WINDOW_SECONDS <= timestamp <= (flow.end_time_epoch or flow.start_time_epoch) + PDU_SBI_WINDOW_SECONDS
                ]
                if len(candidates) == 1:
                    target = candidates[0]
                elif candidates:
                    target = min(
                        candidates,
                        key=lambda flow: abs((flow.start_time_epoch or timestamp) - timestamp),
                    )
        if target is None:
            continue
        target.sbi_calls.append(call)
        target.sbi_call_count += 1
        if call.dst_ip and call.dst_ip not in target.smf_ips:
            target.smf_ips.append(call.dst_ip)
            target.smf_ips.sort()
        if call.request_time_epoch is not None:
            if target.start_time_epoch is None or call.request_time_epoch < target.start_time_epoch:
                target.start_time_epoch = call.request_time_epoch
            if target.end_time_epoch is None or call.request_time_epoch > target.end_time_epoch:
                target.end_time_epoch = call.request_time_epoch
        if call.response_time_epoch is not None and (target.end_time_epoch is None or call.response_time_epoch > target.end_time_epoch):
            target.end_time_epoch = call.response_time_epoch

    if len(grouped) == 1:
        sole_flow = next(iter(grouped.values()))
        if not sole_flow.smf_ips:
            sole_flow.smf_ips = sorted(infer_smf_ips(session))

    return sorted(grouped.values(), key=lambda flow: (flow.start_time_epoch or float("inf"), flow.pdu_session_id))


def correlate_pfcp_to_pdu(
    record_set: ExtractedRecordSet,
    pdu_sessions: list[PDUSessionFlow],
    *,
    warnings: list[str] | None = None,
) -> list[PDUSessionFlow]:
    if not pdu_sessions:
        return pdu_sessions

    smf_ips: set[str] = set()
    for flow in pdu_sessions:
        smf_ips.update(flow.smf_ips)

    pfcp_total = 0
    pfcp_matched = 0
    pfcp_dropped_ip = 0
    pfcp_dropped_time = 0

    for record in record_set.records:
        msg_type = parse_optional_int(record.fields.get("pfcp.msg_type"))
        if msg_type is None:
            continue
        pfcp_total += 1
        src_ip = record.src_ip
        dst_ip = record.dst_ip
        if smf_ips and src_ip not in smf_ips and dst_ip not in smf_ips:
            pfcp_dropped_ip += 1
            continue

        pfcp_flow = PFCPFlow(
            frame_number=record.frame_number,
            time_epoch=record.time_epoch,
            msg_type=msg_type,
            seid=(record.fields.get("pfcp.seid") or None),
            f_seid_ipv4=(record.fields.get("pfcp.f_seid.ipv4") or None),
            cause=parse_optional_int(record.fields.get("pfcp.cause")),
            src_ip=src_ip,
            dst_ip=dst_ip,
        )

        candidates = [
            flow
            for flow in pdu_sessions
            if flow.start_time_epoch is not None
            and flow.start_time_epoch - 1.0 <= record.time_epoch <= (flow.end_time_epoch or flow.start_time_epoch) + PFCP_WINDOW_SECONDS
        ]
        if not candidates and len(pdu_sessions) == 1:
            candidates = [pdu_sessions[0]]
        if not candidates:
            pfcp_dropped_time += 1
            continue

        if len(candidates) == 1:
            target = candidates[0]
            pfcp_flow.matched_by = "single_candidate_time_window"
        else:
            target = min(candidates, key=lambda flow: abs((flow.start_time_epoch or record.time_epoch) - record.time_epoch))
            pfcp_flow.matched_by = "nearest_time_window"

        target.pfcp_flows.append(pfcp_flow)
        target.pfcp_flow_count += 1
        pfcp_matched += 1
        if target.end_time_epoch is None or record.time_epoch > target.end_time_epoch:
            target.end_time_epoch = record.time_epoch

    if warnings is not None and pfcp_total > 0:
        warnings.append(
            f"pfcp_correlation_summary: total={pfcp_total} matched={pfcp_matched} "
            f"dropped_ip_mismatch={pfcp_dropped_ip} dropped_time_window={pfcp_dropped_time}"
        )

    return pdu_sessions
