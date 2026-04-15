from __future__ import annotations

from pathlib import Path
from typing import Sequence

from traceweaver.correlate.pdu import build_pdu_sessions_for_ue, correlate_pfcp_to_pdu
from traceweaver.correlate.sbi import correlate_sbi_to_sessions, pair_sbi_calls
from traceweaver.correlate.ue_sessions import group_ue_sessions
from traceweaver.ingest.records import extract_5gc_records
from traceweaver.models import PDUSessionSet


def extract_pdu_sessions(
    path: str | Path,
    *,
    display_filter: str | None = None,
    decode_as: Sequence[str] | None = None,
    limit: int | None = None,
) -> PDUSessionSet:
    records = extract_5gc_records(
        path,
        display_filter=display_filter,
        decode_as=decode_as,
        limit=limit,
    )
    sessions = group_ue_sessions(records)
    correlate_sbi_to_sessions(pair_sbi_calls(records), sessions)

    pdu_sessions = []
    for session in sessions:
        flows = build_pdu_sessions_for_ue(session)
        correlate_pfcp_to_pdu(records, flows)
        pdu_sessions.extend(flows)

    return PDUSessionSet(
        path=records.path,
        file_name=records.file_name,
        pdu_session_count=len(pdu_sessions),
        warnings=list(records.warnings),
        pdu_sessions=pdu_sessions,
    )
