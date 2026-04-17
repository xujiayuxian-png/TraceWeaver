from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Sequence

from traceweaver.core.tshark import get_tshark_version, resolve_field_aliases, run_tshark_fields_extract, validate_capture_path
from traceweaver.profiles.open5gs_5gc.defaults import DEFAULT_5GC_DECODE_AS, DEFAULT_5GC_DISPLAY_FILTER, PRIMARY_PROTOCOL_ORDER, PROTOCOL_NAME_MAP
from traceweaver.profiles.open5gs_5gc.domain.records import ExtractedRecordSet, NormalizedRecord
from traceweaver.profiles.open5gs_5gc.fields import FIELD_SPECS, SINGLE_VALUE_FIELDS
from traceweaver.utils import parse_optional_float, parse_optional_int

_field_map_cache: tuple[dict[str, str], list[str]] | None = None


def _resolved_field_map() -> tuple[dict[str, str], list[str]]:
    global _field_map_cache
    if _field_map_cache is not None:
        return _field_map_cache
    _field_map_cache = resolve_field_aliases(FIELD_SPECS)
    return _field_map_cache


def clear_field_map_cache() -> None:
    global _field_map_cache
    _field_map_cache = None


def _split_protocols(raw_protocols: str) -> list[str]:
    seen: set[str] = set()
    protocols: list[str] = []
    for token in raw_protocols.split(":"):
        value = PROTOCOL_NAME_MAP.get(token, token)
        if not value or value in seen:
            continue
        seen.add(value)
        protocols.append(value)
    return protocols


def _pick_primary_protocol(protocols: Sequence[str]) -> str | None:
    for protocol in PRIMARY_PROTOCOL_ORDER:
        if protocol in protocols:
            return protocol
    return None


def _normalize_field_value(field_name: str, value: str) -> str:
    raw = (value or "").strip()
    if not raw or field_name not in SINGLE_VALUE_FIELDS or "|" not in raw:
        return raw

    candidates: list[str] = []
    seen: set[str] = set()
    for token in raw.split("|"):
        normalized = token.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        candidates.append(normalized)

    return candidates[0] if candidates else ""


def extract_records(
    path: str | Path,
    *,
    display_filter: str | None = None,
    decode_as: Sequence[str] | None = None,
    limit: int | None = None,
) -> ExtractedRecordSet:
    capture_path = validate_capture_path(Path(path))
    if limit is not None and limit <= 0:
        raise ValueError("limit must be > 0")

    resolved_fields, unresolved_fields = _resolved_field_map()
    ordered_pairs = [(canonical, resolved_fields[canonical]) for canonical, _aliases in FIELD_SPECS if canonical in resolved_fields]
    canonical_order = [canonical for canonical, _actual in ordered_pairs]
    actual_fields = [actual for _canonical, actual in ordered_pairs]

    resolved_display_filter = display_filter if display_filter is not None else DEFAULT_5GC_DISPLAY_FILTER
    resolved_decode_as = tuple(decode_as or DEFAULT_5GC_DECODE_AS)
    output = run_tshark_fields_extract(
        capture_path,
        display_filter=resolved_display_filter,
        decode_as=resolved_decode_as,
        actual_fields=actual_fields,
    )

    records: list[NormalizedRecord] = []
    reader = csv.reader(io.StringIO(output), delimiter="\t", quotechar='"')
    for parts in reader:
        if not parts:
            continue
        raw_fields = {canonical: "" for canonical, _aliases in FIELD_SPECS}
        for index, canonical in enumerate(canonical_order):
            raw_value = parts[index] if index < len(parts) else ""
            raw_fields[canonical] = _normalize_field_value(canonical, raw_value)

        protocols = _split_protocols(raw_fields["frame.protocols"])
        frame_number = parse_optional_int(raw_fields["frame.number"])
        time_epoch = parse_optional_float(raw_fields["frame.time_epoch"])
        if frame_number is None or time_epoch is None:
            continue

        src_ip = raw_fields["ip.src"] or raw_fields["ipv6.src"] or None
        dst_ip = raw_fields["ip.dst"] or raw_fields["ipv6.dst"] or None
        tcp_src = parse_optional_int(raw_fields["tcp.srcport"])
        tcp_dst = parse_optional_int(raw_fields["tcp.dstport"])
        sctp_src = parse_optional_int(raw_fields["sctp.srcport"])
        sctp_dst = parse_optional_int(raw_fields["sctp.dstport"])

        if tcp_src is not None or tcp_dst is not None:
            transport_protocol = "tcp"
            src_port = tcp_src
            dst_port = tcp_dst
        elif sctp_src is not None or sctp_dst is not None:
            transport_protocol = "sctp"
            src_port = sctp_src
            dst_port = sctp_dst
        else:
            transport_protocol = None
            src_port = None
            dst_port = None

        records.append(
            NormalizedRecord(
                frame_number=frame_number,
                time_epoch=time_epoch,
                time_relative=parse_optional_float(raw_fields["frame.time_relative"]),
                protocols=protocols,
                primary_protocol=_pick_primary_protocol(protocols),
                src_ip=src_ip,
                dst_ip=dst_ip,
                src_port=src_port,
                dst_port=dst_port,
                transport_protocol=transport_protocol,
                fields=raw_fields,
            )
        )
        if limit is not None and len(records) >= limit:
            break

    warnings: list[str] = []
    if unresolved_fields:
        warnings.append("some requested tshark fields were unavailable and were emitted as empty strings")

    return ExtractedRecordSet(
        path=str(capture_path),
        file_name=capture_path.name,
        display_filter=resolved_display_filter,
        decode_as=list(resolved_decode_as),
        tshark_version=get_tshark_version(),
        resolved_fields=resolved_fields,
        unresolved_fields=unresolved_fields,
        warnings=warnings,
        record_count=len(records),
        records=records,
    )
