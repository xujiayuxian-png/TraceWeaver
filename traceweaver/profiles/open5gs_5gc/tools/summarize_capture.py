"""`summarize_capture`: capture-wide factual summary."""
from __future__ import annotations
from collections import Counter, deque
from typing import Any
from traceweaver.core.protocols import Tool, ToolContext, ToolResult, ToolSpec

# Per-UE events list is split into a head (first N) + tail (last N) view so the
# LLM can see both the start of the flow and any late events such as
# DEREGISTRATION_REQUEST or PDU session teardown. If the total number of UE
# events exceeds head + tail, the gap is reported via `events_truncated_count`
# so the LLM knows there is more in the middle and can drill down with
# `get_ue_timeline` if needed.
_MAX_UE_EVENTS_HEAD = 25
_MAX_UE_EVENTS_TAIL = 25


def _http_status(raw: Any) -> int | None:
    if raw is None:
        return None
    try:
        return int(str(raw).split(",", 1)[0])
    except ValueError:
        return None


class SummarizeCaptureTool(Tool):
    spec = ToolSpec(
        name="summarize_capture",
        description=(
            "Return capture-wide factual inventory for the Open5GS 5GC "
            "profile: event_inventory (every NAS/NGAP/PFCP event with "
            "first/last seq), ue_overview (per-UE event list split into "
            "events_head and events_tail, plus events_truncated_count for "
            "the gap), and neutral capture_signals. Always inspect "
            "events_tail before concluding success: late events such as "
            "DEREGISTRATION_REQUEST or PDU teardown live there. This tool "
            "does not produce verdicts, root causes, or confidence."
        ),
        parameters_schema={"type": "object", "properties": {}, "required": []},
    )

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        if ctx.source_handle is None:
            return ToolResult(
                data={
                    "event_inventory": [],
                    "ue_overview": [],
                    "capture_signals": {},
                    "hint": "no source_handle",
                }
            )

        record_count = 0
        event_counts: Counter[str] = Counter()
        event_first_seq: dict[str, int] = {}
        event_last_seq: dict[str, int] = {}
        layer_counts: Counter[str] = Counter()
        ue_slots: dict[str, dict[str, Any]] = {}
        sbi_calls: dict[tuple[str, str], dict[str, Any]] = {}
        pfcp_counts: Counter[str] = Counter()

        for rec in ctx.source_handle.iter_records():
            record_count += 1
            f = rec.fields
            layer = str(f.get("protocol_layer") or "other")
            layer_counts[layer] += 1
            ev_raw = f.get("event")
            ev = str(ev_raw) if ev_raw else None
            if ev is not None:
                event_counts[ev] += 1
                event_first_seq.setdefault(ev, rec.seq)
                event_last_seq[ev] = rec.seq

            ran = f.get("ran_ue_ngap_id")
            amf = f.get("amf_ue_ngap_id")
            if ev is not None and (ran is not None or amf is not None):
                key = f"ran:{ran}" if ran is not None else f"amf:{amf}"
                slot = ue_slots.setdefault(
                    key,
                    {
                        "ran_ue_ngap_id": None if ran is None else str(ran),
                        "amf_ue_ngap_id": None if amf is None else str(amf),
                        "first_seq": rec.seq,
                        "last_seq": rec.seq,
                        "event_count": 0,
                        "event_counts": Counter(),
                        "events_head": [],
                        "events_tail": deque(maxlen=_MAX_UE_EVENTS_TAIL),
                    },
                )
                if slot["ran_ue_ngap_id"] is None and ran is not None:
                    slot["ran_ue_ngap_id"] = str(ran)
                if slot["amf_ue_ngap_id"] is None and amf is not None:
                    slot["amf_ue_ngap_id"] = str(amf)
                slot["last_seq"] = rec.seq
                slot["event_count"] += 1
                slot["event_counts"][ev] += 1
                if len(slot["events_head"]) < _MAX_UE_EVENTS_HEAD:
                    slot["events_head"].append(ev)
                else:
                    slot["events_tail"].append(ev)

            pfcp_name = f.get("pfcp_msg_name")
            if pfcp_name:
                pfcp_counts[str(pfcp_name)] += 1

            stream_id = f.get("http2.streamid")
            if stream_id:
                key = (str(f.get("tcp.stream") or ""), str(stream_id))
                call = sbi_calls.setdefault(
                    key,
                    {"method": None, "path": None, "status": None},
                )
                if f.get("http2.headers.method") and call["method"] is None:
                    call["method"] = str(f.get("http2.headers.method"))
                if f.get("http2.headers.path") and call["path"] is None:
                    call["path"] = str(f.get("http2.headers.path"))
                status = _http_status(f.get("http2.headers.status"))
                if status is not None and call["status"] is None:
                    call["status"] = status

        event_inventory = [
            {
                "event": event,
                "count": event_counts[event],
                "first_seq": event_first_seq[event],
                "last_seq": event_last_seq[event],
            }
            for event in sorted(event_counts, key=lambda e: event_first_seq[e])
        ]
        ue_overview = []
        for slot in sorted(ue_slots.values(), key=lambda s: s["first_seq"]):
            head = list(slot["events_head"])
            tail = list(slot["events_tail"])
            total = slot["event_count"]
            truncated = max(0, total - len(head) - len(tail))
            ue_overview.append(
                {
                    "ran_ue_ngap_id": slot["ran_ue_ngap_id"],
                    "amf_ue_ngap_id": slot["amf_ue_ngap_id"],
                    "first_seq": slot["first_seq"],
                    "last_seq": slot["last_seq"],
                    "event_count": total,
                    "event_counts": dict(slot["event_counts"]),
                    "events_head": head,
                    "events_tail": tail,
                    "events_truncated_count": truncated,
                }
            )

        sbi_http_request_count = sum(1 for c in sbi_calls.values() if c["method"])
        sbi_http_response_count = sum(1 for c in sbi_calls.values() if c["status"] is not None)
        sbi_http_4xx_count = sum(
            1 for c in sbi_calls.values()
            if isinstance(c["status"], int) and 400 <= c["status"] <= 499
        )
        sbi_http_5xx_count = sum(
            1 for c in sbi_calls.values()
            if isinstance(c["status"], int) and 500 <= c["status"] <= 599
        )
        sbi_unanswered_request_count = sum(
            1 for c in sbi_calls.values()
            if c["method"] and c["status"] is None
        )

        repeated_registration_request_ue_count = sum(
            1 for slot in ue_overview
            if slot["event_counts"].get("REGISTRATION_REQUEST", 0) > 1
        )
        pfcp_session_establishment_request_count = pfcp_counts[
            "SESSION_ESTABLISHMENT_REQUEST"
        ]
        pfcp_session_establishment_response_count = pfcp_counts[
            "SESSION_ESTABLISHMENT_RESPONSE"
        ]
        pdu_request_count = event_counts["PDU_SESSION_ESTABLISHMENT_REQUEST"]
        pdu_accept_count = event_counts["PDU_SESSION_ESTABLISHMENT_ACCEPT"]
        pdu_reject_count = event_counts["PDU_SESSION_ESTABLISHMENT_REJECT"]
        pdu_terminal_count = pdu_accept_count + pdu_reject_count

        capture_signals = {
            "record_count": record_count,
            "event_count": sum(event_counts.values()),
            "ue_count": len(ue_overview),
            "protocol_layer_counts": dict(layer_counts),
            "registration_request_count": event_counts["REGISTRATION_REQUEST"],
            "registration_accept_count": event_counts["REGISTRATION_ACCEPT"],
            "registration_complete_count": event_counts["REGISTRATION_COMPLETE"],
            "registration_reject_count": event_counts["REGISTRATION_REJECT"],
            "authentication_failure_count": event_counts["AUTHENTICATION_FAILURE"],
            "security_mode_reject_count": event_counts["SECURITY_MODE_REJECT"],
            "service_reject_count": event_counts["SERVICE_REJECT"],
            "pdu_session_establishment_request_count": pdu_request_count,
            "pdu_session_establishment_accept_count": pdu_accept_count,
            "pdu_session_establishment_reject_count": pdu_reject_count,
            "pdu_session_establishment_request_without_terminal_count": max(
                0, pdu_request_count - pdu_terminal_count
            ),
            "deregistration_event_count": sum(
                count for event, count in event_counts.items()
                if event.startswith("DEREGISTRATION_")
            ),
            "ngap_ue_context_release_count": event_counts["NGAP_UE_CONTEXT_RELEASE"],
            "pfcp_message_count": sum(pfcp_counts.values()),
            "pfcp_session_establishment_request_count": pfcp_session_establishment_request_count,
            "pfcp_session_establishment_response_count": pfcp_session_establishment_response_count,
            "has_pfcp_session_establishment_imbalance": (
                pfcp_session_establishment_request_count
                != pfcp_session_establishment_response_count
            ),
            "pfcp_session_deletion_request_count": pfcp_counts[
                "SESSION_DELETION_REQUEST"
            ],
            "pfcp_session_deletion_response_count": pfcp_counts[
                "SESSION_DELETION_RESPONSE"
            ],
            "sbi_http_request_count": sbi_http_request_count,
            "sbi_http_response_count": sbi_http_response_count,
            "sbi_http_4xx_count": sbi_http_4xx_count,
            "sbi_http_5xx_count": sbi_http_5xx_count,
            "sbi_unanswered_request_count": sbi_unanswered_request_count,
            "repeated_registration_request_ue_count": repeated_registration_request_ue_count,
            "has_multiple_ue_paths": len(ue_overview) > 1,
        }

        return ToolResult(
            data={
                "event_inventory": event_inventory,
                "ue_overview": ue_overview,
                "capture_signals": capture_signals,
            }
        )


__all__ = ["SummarizeCaptureTool"]
