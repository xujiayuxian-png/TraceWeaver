from __future__ import annotations

from pathlib import Path
from typing import Sequence

from traceweaver.correlate.pdu import build_pdu_sessions_for_ue, correlate_pfcp_to_pdu
from traceweaver.correlate import correlate_sbi_to_sessions, group_ue_sessions, pair_sbi_calls
from traceweaver.ingest.records import extract_5gc_records
from traceweaver.models import UESessionSet


def extract_ue_sessions(
    path: str | Path,
    *,
    display_filter: str | None = None,
    decode_as: Sequence[str] | None = None,
    limit: int | None = None,
) -> UESessionSet:
    records = extract_5gc_records(
        path,
        display_filter=display_filter,
        decode_as=decode_as,
        limit=limit,
    )
    warnings = list(records.warnings)
    sessions = group_ue_sessions(records, warnings=warnings)
    correlate_sbi_to_sessions(pair_sbi_calls(records), sessions, warnings=warnings)
    for session in sessions:
        session.pdu_sessions = build_pdu_sessions_for_ue(session)
        correlate_pfcp_to_pdu(records, session.pdu_sessions, warnings=warnings)
        session.pdu_session_count = len(session.pdu_sessions)
    return UESessionSet(
        path=records.path,
        file_name=records.file_name,
        session_count=len(sessions),
        warnings=warnings,
        sessions=sessions,
    )
