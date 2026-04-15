from __future__ import annotations

import csv
import io
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Sequence

from traceweaver.models import ExtractedRecordSet, NormalizedRecord
from traceweaver.tshark.tools import ExternalToolError, get_tshark_version, list_tshark_fields

SUPPORTED_CAPTURE_SUFFIXES = {".pcap", ".pcapng"}
DEFAULT_5GC_DISPLAY_FILTER = "ngap || nas-5gs || http2 || pfcp"
DEFAULT_5GC_DECODE_AS = ("tcp.port==7777,http2",)
SINGLE_VALUE_FIELDS = {
     "frame.number",
     "frame.time_epoch",
     "frame.time_relative",
     "ip.src",
     "ip.dst",
     "ipv6.src",
     "ipv6.dst",
     "tcp.srcport",
     "tcp.dstport",
     "tcp.stream",
     "sctp.srcport",
     "sctp.dstport",
     "ngap.procedureCode",
     "ngap.RAN_UE_NGAP_ID",
     "ngap.AMF_UE_NGAP_ID",
     "ngap.pDUSessionID",
     "nas_5gs.mm.message_type",
     "nas_5gs.mm.5gmm_cause",
     "nas_5gs.sm.message_type",
     "nas_5gs.sm.5gsm_cause",
     "nas_5gs.mm.suci.scheme_output",
     "nas_5gs.mm.type_of_identity",
     "nas_5gs.pdu_session_id",
     "http2.headers.method",
     "http2.headers.path",
     "http2.headers.status",
     "http2.headers.host",
     "http2.headers.scheme",
     "http2.headers.authority",
     "http2.streamid",
     "pfcp.msg_type",
     "pfcp.seid",
     "pfcp.f_seid.ipv4",
     "pfcp.cause",
 }

FIELD_SPECS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("frame.number", ("frame.number",)),
    ("frame.time_epoch", ("frame.time_epoch",)),
    ("frame.time_relative", ("frame.time_relative",)),
    ("frame.protocols", ("frame.protocols",)),
    ("frame.info", ("frame.info", "_ws.col.Info")),
    ("ip.src", ("ip.src",)),
    ("ip.dst", ("ip.dst",)),
    ("ipv6.src", ("ipv6.src",)),
    ("ipv6.dst", ("ipv6.dst",)),
    ("tcp.srcport", ("tcp.srcport",)),
    ("tcp.dstport", ("tcp.dstport",)),
    ("tcp.stream", ("tcp.stream",)),
    ("sctp.srcport", ("sctp.srcport",)),
    ("sctp.dstport", ("sctp.dstport",)),
    ("ngap.procedureCode", ("ngap.procedureCode",)),
    ("ngap.RAN_UE_NGAP_ID", ("ngap.RAN_UE_NGAP_ID",)),
    ("ngap.AMF_UE_NGAP_ID", ("ngap.AMF_UE_NGAP_ID",)),
    ("ngap.pDUSessionID", ("ngap.pDUSessionID",)),
    ("nas_5gs.mm.message_type", ("nas-5gs.mm.message_type", "nas_5gs.mm.message_type")),
    ("nas_5gs.mm.5gmm_cause", ("nas-5gs.mm.5gmm_cause", "nas_5gs.mm.5gmm_cause")),
    ("nas_5gs.sm.message_type", ("nas-5gs.sm.message_type", "nas_5gs.sm.message_type")),
    ("nas_5gs.sm.5gsm_cause", ("nas-5gs.sm.5gsm_cause", "nas_5gs.sm.5gsm_cause")),
    ("nas_5gs.mm.suci.scheme_output", ("nas-5gs.mm.suci.scheme_output", "nas_5gs.mm.suci.scheme_output")),
    ("nas_5gs.mm.type_of_identity", ("nas-5gs.mm.type_of_identity", "nas_5gs.mm.type_of_identity")),
    ("nas_5gs.pdu_session_id", ("nas-5gs.pdu_session_id", "nas_5gs.pdu_session_id")),
    ("http2.headers.method", ("http2.headers.method",)),
    ("http2.headers.path", ("http2.headers.path",)),
    ("http2.headers.status", ("http2.headers.status",)),
    ("http2.headers.host", ("http2.headers.host",)),
    ("http2.headers.scheme", ("http2.headers.scheme",)),
    ("http2.headers.authority", ("http2.headers.authority",)),
    ("http2.streamid", ("http2.streamid",)),
    ("pfcp.msg_type", ("pfcp.msg_type",)),
    ("pfcp.seid", ("pfcp.seid",)),
    ("pfcp.f_seid.ipv4", ("pfcp.f_seid.ipv4",)),
    ("pfcp.cause", ("pfcp.cause",)),
)

PRIMARY_PROTOCOL_ORDER = ("nas_5gs", "ngap", "http2", "pfcp")
PROTOCOL_NAME_MAP = {"nas-5gs": "nas_5gs"}


@lru_cache(maxsize=1)
def _resolved_field_map() -> tuple[dict[str, str], list[str]]:
    available = list_tshark_fields()
    resolved: dict[str, str] = {}
    unresolved: list[str] = []
    for canonical, aliases in FIELD_SPECS:
        actual = next((alias for alias in aliases if alias in available), None)
        if actual is None:
            unresolved.append(canonical)
            continue
        resolved[canonical] = actual
    return resolved, unresolved


def _validate_capture_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"capture file not found: {resolved}")
    if not resolved.is_file():
        raise IsADirectoryError(f"capture path is not a file: {resolved}")
    if resolved.suffix.lower() not in SUPPORTED_CAPTURE_SUFFIXES:
        raise ValueError(f"unsupported capture suffix: {resolved.suffix}")
    return resolved


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


def _parse_optional_int(value: str) -> int | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return int(raw, 0)
    except ValueError:
        return None


def _parse_optional_float(value: str) -> float | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
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


def _run_tshark_extract(
    path: Path,
    *,
    display_filter: str,
    decode_as: Sequence[str],
    actual_fields: Sequence[str],
) -> str:
    args = ["tshark"]
    for rule in decode_as:
        rule_value = (rule or "").strip()
        if rule_value:
            args.extend(["-d", rule_value])
    args.extend(["-r", str(path)])
    if display_filter:
        args.extend(["-Y", display_filter])
    args.extend(
        [
            "-T",
            "fields",
            "-E",
            "separator=\t",
            "-E",
            "quote=d",
            "-E",
            "occurrence=a",
            "-E",
            "aggregator=|",
        ]
    )
    for field_name in actual_fields:
        args.extend(["-e", field_name])

    completed = subprocess.run(args, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        raise ExternalToolError(
            f"command failed: {' '.join(args)}\nstdout: {completed.stdout}\nstderr: {completed.stderr}"
        )
    return completed.stdout


def extract_5gc_records(
    path: str | Path,
    *,
    display_filter: str = DEFAULT_5GC_DISPLAY_FILTER,
    decode_as: Sequence[str] | None = None,
    limit: int | None = None,
) -> ExtractedRecordSet:
    capture_path = _validate_capture_path(Path(path))
    if limit is not None and limit <= 0:
        raise ValueError("limit must be > 0")

    resolved_fields, unresolved_fields = _resolved_field_map()
    ordered_pairs = [(canonical, resolved_fields[canonical]) for canonical, _aliases in FIELD_SPECS if canonical in resolved_fields]
    canonical_order = [canonical for canonical, _actual in ordered_pairs]
    actual_fields = [actual for _canonical, actual in ordered_pairs]

    output = _run_tshark_extract(
        capture_path,
        display_filter=display_filter,
        decode_as=tuple(decode_as or DEFAULT_5GC_DECODE_AS),
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
        frame_number = _parse_optional_int(raw_fields["frame.number"])
        time_epoch = _parse_optional_float(raw_fields["frame.time_epoch"])
        if frame_number is None or time_epoch is None:
            continue

        src_ip = raw_fields["ip.src"] or raw_fields["ipv6.src"] or None
        dst_ip = raw_fields["ip.dst"] or raw_fields["ipv6.dst"] or None
        tcp_src = _parse_optional_int(raw_fields["tcp.srcport"])
        tcp_dst = _parse_optional_int(raw_fields["tcp.dstport"])
        sctp_src = _parse_optional_int(raw_fields["sctp.srcport"])
        sctp_dst = _parse_optional_int(raw_fields["sctp.dstport"])

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
                time_relative=_parse_optional_float(raw_fields["frame.time_relative"]),
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
        display_filter=display_filter,
        decode_as=list(decode_as or DEFAULT_5GC_DECODE_AS),
        tshark_version=get_tshark_version(),
        resolved_fields=resolved_fields,
        unresolved_fields=unresolved_fields,
        warnings=warnings,
        record_count=len(records),
        records=records,
    )
