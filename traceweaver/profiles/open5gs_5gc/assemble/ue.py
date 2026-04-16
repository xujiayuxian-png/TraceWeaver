from __future__ import annotations

from traceweaver.profiles.open5gs_5gc.domain.records import ExtractedRecordSet
from traceweaver.profiles.open5gs_5gc.domain.sessions import UESession
from traceweaver.profiles.open5gs_5gc.events.identify import detect_events_for_record

TIME_WINDOW_SECONDS = 2.0


def _normalize_id(value: str | None) -> str | None:
    normalized = (value or "").strip()
    return normalized or None


def _session_id(ran_ue_ngap_id: str | None, amf_ue_ngap_id: str | None) -> str:
    parts: list[str] = []
    if ran_ue_ngap_id:
        parts.append(f"ran-{ran_ue_ngap_id}")
    if amf_ue_ngap_id:
        parts.append(f"amf-{amf_ue_ngap_id}")
    return "__".join(parts) if parts else "unknown"


def group_ue_sessions(
    record_set: ExtractedRecordSet,
    *,
    warnings: list[str] | None = None,
) -> list[UESession]:
    sessions: dict[tuple[str | None, str | None], UESession] = {}
    ran_index: dict[str, tuple[str | None, str | None]] = {}
    amf_index: dict[str, tuple[str | None, str | None]] = {}

    def register_key(key: tuple[str | None, str | None], session: UESession) -> None:
        sessions[key] = session
        if key[0]:
            ran_index[key[0]] = key
        if key[1]:
            amf_index[key[1]] = key

    def remove_key(key: tuple[str | None, str | None]) -> UESession:
        session = sessions.pop(key)
        ran_key, amf_key = key
        if ran_key and ran_index.get(ran_key) == key:
            del ran_index[ran_key]
        if amf_key and amf_index.get(amf_key) == key:
            del amf_index[amf_key]
        return session

    def append_record(session: UESession, record) -> None:
        if session.start_time_epoch is None or record.time_epoch < session.start_time_epoch:
            session.start_time_epoch = record.time_epoch
        if session.end_time_epoch is None or record.time_epoch > session.end_time_epoch:
            session.end_time_epoch = record.time_epoch

        suci = _normalize_id(record.fields.get("nas_5gs.mm.suci.scheme_output"))
        if suci and not session.suci:
            session.suci = suci

        session.records.append(record)
        session.frame_numbers.append(record.frame_number)
        session.source_record_count += 1

        events = detect_events_for_record(record)
        if events:
            session.events.extend(events)
            session.event_count += len(events)

    orphan_attached = 0
    orphan_dropped = 0

    for record in record_set.records:
        if record.primary_protocol not in {"ngap", "nas_5gs"}:
            continue

        ran_ue_ngap_id = _normalize_id(record.fields.get("ngap.RAN_UE_NGAP_ID"))
        amf_ue_ngap_id = _normalize_id(record.fields.get("ngap.AMF_UE_NGAP_ID"))

        if not ran_ue_ngap_id and not amf_ue_ngap_id:
            if record.primary_protocol == "nas_5gs" and sessions:
                candidates = [
                    session
                    for session in sessions.values()
                    if session.start_time_epoch is not None
                    and session.start_time_epoch - 1.0 <= record.time_epoch <= (session.end_time_epoch or session.start_time_epoch) + TIME_WINDOW_SECONDS
                ]
                if len(candidates) == 1:
                    append_record(candidates[0], record)
                    orphan_attached += 1
                elif len(candidates) == 0 and len(sessions) == 1:
                    append_record(next(iter(sessions.values())), record)
                    orphan_attached += 1
                else:
                    orphan_dropped += 1
            else:
                orphan_dropped += 1
            continue

        key: tuple[str | None, str | None]
        if ran_ue_ngap_id and amf_ue_ngap_id:
            key = (ran_ue_ngap_id, amf_ue_ngap_id)
            if key not in sessions:
                prior_key = ran_index.get(ran_ue_ngap_id) or amf_index.get(amf_ue_ngap_id)
                if prior_key and prior_key != key:
                    prior_ran, prior_amf = prior_key
                    is_upgrade = prior_ran is None or prior_amf is None
                    if is_upgrade:
                        session = remove_key(prior_key)
                        session.ran_ue_ngap_id = ran_ue_ngap_id
                        session.amf_ue_ngap_id = amf_ue_ngap_id
                        session.session_id = _session_id(ran_ue_ngap_id, amf_ue_ngap_id)
                        register_key(key, session)
        elif ran_ue_ngap_id:
            key = ran_index.get(ran_ue_ngap_id, (ran_ue_ngap_id, None))
        else:
            key = amf_index.get(amf_ue_ngap_id, (None, amf_ue_ngap_id))

        if key not in sessions:
            register_key(
                key,
                UESession(
                    session_id=_session_id(key[0], key[1]),
                    ran_ue_ngap_id=key[0],
                    amf_ue_ngap_id=key[1],
                ),
            )

        append_record(sessions[key], record)

    if warnings is not None:
        if orphan_dropped > 0:
            warnings.append(
                f"ue_session_grouping: {orphan_dropped} NAS frame(s) without UE NGAP ID could not be attached to any session"
            )
        if orphan_attached > 0:
            warnings.append(
                f"ue_session_grouping: {orphan_attached} NAS frame(s) without UE NGAP ID attached via time window heuristic"
            )

    return sorted(
        sessions.values(),
        key=lambda session: (
            session.start_time_epoch if session.start_time_epoch is not None else float("inf"),
            session.session_id,
        ),
    )
