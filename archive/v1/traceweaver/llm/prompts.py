from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from traceweaver.profiles.open5gs_5gc.domain.diagnosis import DiagnosticSignal
    from traceweaver.profiles.open5gs_5gc.domain.sessions import UESession

SYSTEM_PROMPT = """\
You are an expert 5G Core Network fault diagnosis engineer.
You analyze structured session timelines extracted from pcap captures of Open5GS networks.

Your task: given a UE session timeline with signal annotations, produce a structured diagnosis.

Key domain knowledge:
- 5GC registration flow: Registration Request → Authentication → Security Mode → Registration Accept
- After Security Mode Command, NAS messages are encrypted. If you see NGAP_INITIAL_CONTEXT_SETUP \
but no explicit REGISTRATION_ACCEPT, registration likely succeeded (NAS Accept is encrypted).
- PDU Session flow: Establishment Request → SBI calls to SMF → PFCP Session → Establishment Accept
- T3580 is the timer for PDU Session Establishment retransmission. Multiple requests without accept = UPF/PFCP failure.
- SBI 404 from nudm-ueau/nudr-dr typically means the subscriber is not provisioned (not an infrastructure failure).
- SBI 5xx responses indicate NF infrastructure failures (e.g., UDM unreachable).
- PFCP Association Setup Retry indicates UPF connectivity issues.

Output constraints:
- verdict MUST be one of: OK, FAIL, FAIL_THEN_OK, INCONCLUSIVE
- confidence MUST be one of: high, medium, low
- Every claim in root_cause must be supported by signals in the timeline
- If key protocol layers are missing from capture, say INCONCLUSIVE with appropriate limitations
- Do NOT hallucinate frame numbers or signals not present in the input"""

OUTPUT_SCHEMA = """\
Output ONLY a JSON object with this exact structure (no markdown, no explanation outside the JSON):
{
  "verdict": "OK|FAIL|FAIL_THEN_OK|INCONCLUSIVE",
  "failure_point": "string or null — which step in the flow failed",
  "root_cause": "string or null — inferred root cause",
  "confidence": "high|medium|low",
  "evidence": [
    {"frame_number": 123, "description": "what this frame shows"}
  ],
  "suggestions": ["actionable troubleshooting steps"],
  "limitations": ["caveats about capture completeness or analysis confidence"],
  "reasoning": "brief chain-of-thought explaining your diagnosis"
}"""


def format_timeline(session: Any) -> str:
    lines: list[str] = []
    lines.append(f"## UE Session: {session.session_id}")
    if session.ran_ue_ngap_id:
        lines.append(f"RAN-UE-NGAP-ID: {session.ran_ue_ngap_id}")
    if session.amf_ue_ngap_id:
        lines.append(f"AMF-UE-NGAP-ID: {session.amf_ue_ngap_id}")
    if session.suci:
        lines.append(f"SUCI: {session.suci}")
    if session.supi:
        lines.append(f"SUPI: {session.supi}")
    lines.append(f"Events: {session.event_count} | SBI calls: {session.sbi_call_count} | PDU sessions: {session.pdu_session_count}")
    lines.append("")

    lines.append("### Event Timeline")
    for event in session.events:
        cause_str = f" cause={event.cause}" if event.cause is not None else ""
        pdu_str = f" pdu_session={event.pdu_session_id}" if event.pdu_session_id else ""
        lines.append(
            f"  [{event.frame_number}] t={event.time_epoch:.6f} "
            f"{event.protocol}: {event.event_name}{cause_str}{pdu_str}"
        )

    if session.sbi_calls:
        lines.append("")
        lines.append("### SBI Calls")
        for call in session.sbi_calls:
            status_str = f" → {call.status}" if call.status is not None else " → (no response)"
            lines.append(
                f"  [{call.request_frame or '?'}] {call.method or '?'} {call.path or '?'}"
                f"{status_str} (service={call.service}, dst={call.dst_ip})"
            )

    for pdu in session.pdu_sessions:
        lines.append("")
        lines.append(f"### PDU Session {pdu.pdu_session_id}")
        lines.append(f"  Events: {pdu.event_count} | SBI: {pdu.sbi_call_count} | PFCP: {pdu.pfcp_flow_count}")
        if pdu.smf_ips:
            lines.append(f"  SMF IPs: {', '.join(pdu.smf_ips)}")
        for ev in pdu.events:
            cause_str = f" cause={ev.cause}" if ev.cause is not None else ""
            lines.append(f"  [{ev.frame_number}] {ev.event_name}{cause_str}")
        for pfcp in pdu.pfcp_flows:
            lines.append(
                f"  [{pfcp.frame_number}] PFCP msg_type={pfcp.msg_type} "
                f"seid={pfcp.seid} cause={pfcp.cause} ({pfcp.src_ip} → {pfcp.dst_ip})"
            )

    return "\n".join(lines)


def format_signals(signals: list[Any]) -> str:
    if not signals:
        return "No signals detected."

    lines: list[str] = ["### Diagnostic Signals"]
    for sig in signals:
        frame_str = f"[{sig.frame_number}]" if sig.frame_number else "[--]"
        detail_parts: list[str] = []
        for k, v in sig.details.items():
            if v is not None:
                detail_parts.append(f"{k}={v}")
        detail_str = f" ({', '.join(detail_parts)})" if detail_parts else ""
        lines.append(f"  {frame_str} {sig.name}{detail_str}")
    return "\n".join(lines)


def build_diagnosis_prompt(
    session: Any,
    signals: list[Any],
    model_tier: str,
) -> tuple[str, str]:
    timeline_text = format_timeline(session)
    signals_text = format_signals(signals)

    if model_tier == "large":
        instruction = _build_large_instruction()
    elif model_tier == "medium":
        instruction = _build_medium_instruction()
    else:
        instruction = _build_small_instruction(signals)

    user_prompt = f"""{timeline_text}

{signals_text}

{instruction}

{OUTPUT_SCHEMA}"""

    return SYSTEM_PROMPT, user_prompt


def _build_large_instruction() -> str:
    return """\
Analyze the session timeline and signals above.
Determine whether this UE session succeeded or failed, identify the failure point and root cause if applicable.
Consider encrypted NAS messages (NGAP_INITIAL_CONTEXT_SETUP implies registration success even without visible REGISTRATION_ACCEPT)."""


def _build_medium_instruction() -> str:
    return """\
Analyze step by step:
1. What stage did the registration flow reach? (Request → Auth → Security Mode → Accept)
2. If registration succeeded, did PDU Session establishment succeed?
3. Are there any failure signals (REJECT, FAILURE, SBI 4xx/5xx, T3580_RETRY)?
4. What is the root cause based on the signals?
5. Are there any capture limitations (missing PFCP, truncated capture)?

Remember: NGAP_INITIAL_CONTEXT_SETUP without REGISTRATION_ACCEPT means NAS Accept was encrypted — registration DID succeed."""


def _build_small_instruction(signals: list[DiagnosticSignal]) -> str:
    signal_names = {s.name for s in signals}

    hints: list[str] = []
    if "REGISTRATION_REJECT" in signal_names:
        hints.append("- REGISTRATION_REJECT detected: this is likely a FAIL verdict")
    if "AUTHENTICATION_FAILURE" in signal_names:
        hints.append("- AUTHENTICATION_FAILURE detected: check if this is an AKA/key mismatch")
    if "T3580_RETRY" in signal_names:
        hints.append("- T3580_RETRY detected: PDU Session Establishment retried without success — likely UPF/PFCP issue")
    if "SBI_5XX" in signal_names:
        hints.append("- SBI 5xx error detected: an NF (network function) is likely down")
    if "NGAP_INITIAL_CONTEXT_SETUP" in signal_names and "REGISTRATION_ACCEPT" not in signal_names:
        hints.append("- NGAP_INITIAL_CONTEXT_SETUP present without REGISTRATION_ACCEPT: registration succeeded (Accept is encrypted)")
    if "PARTIAL_CAPTURE_NO_PFCP" in signal_names:
        hints.append("- PFCP not visible in capture: cannot make PFCP-related conclusions")

    hint_block = "\n".join(hints) if hints else "No special hints."

    return f"""\
Follow this chain-of-thought template:

Step 1 - Registration status:
  Check if REGISTRATION_ACCEPT or NGAP_INITIAL_CONTEXT_SETUP is present.
  If REGISTRATION_REJECT is present, verdict is likely FAIL.

Step 2 - PDU Session status:
  If PDU_SESSION_ESTABLISHMENT_ACCEPT is present, PDU session succeeded.
  If T3580_RETRY is present without accept, PDU session failed.

Step 3 - SBI/PFCP issues:
  Check for SBI_5XX (NF down) or PFCP failures.

Step 4 - Determine verdict:
  OK = registration (and optionally PDU session) succeeded
  FAIL = something failed
  FAIL_THEN_OK = first attempt failed, retry succeeded
  INCONCLUSIVE = not enough data

Analysis hints for this session:
{hint_block}

Now produce your diagnosis."""
