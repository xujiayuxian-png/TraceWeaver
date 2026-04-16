from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from traceweaver.core.tshark import (
    get_capinfos_version,
    get_tshark_version,
    has_matching_frames,
    is_minimum_version,
    read_capinfos_table,
)

SUPPORTED_CAPTURE_SUFFIXES = {".pcap", ".pcapng"}
MINIMUM_RECOMMENDED_TSHARK_VERSION = "4.0.0"
HTTP2_DECODE_AS_RULE = "tcp.port==7777,http2"


class ProtocolPresence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ngap: bool
    nas_5gs: bool
    http2: bool
    http2_forced_on_7777: bool
    pfcp: bool


class ToolingInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tshark_version: str
    capinfos_version: str
    tshark_minimum_recommended: str
    tshark_meets_minimum_recommended: bool


class CaptureInspection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    file_name: str
    file_size_bytes: int
    packet_count: int
    duration_seconds: float
    start_time_epoch: float
    end_time_epoch: float
    protocols: ProtocolPresence
    recommended_decode_as: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    tooling: ToolingInfo


def _validate_capture_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"capture file not found: {resolved}")
    if not resolved.is_file():
        raise IsADirectoryError(f"capture path is not a file: {resolved}")
    if resolved.suffix.lower() not in SUPPORTED_CAPTURE_SUFFIXES:
        raise ValueError(f"unsupported capture suffix: {resolved.suffix}")
    return resolved


def inspect_capture(path: str | Path) -> CaptureInspection:
    capture_path = _validate_capture_path(Path(path))

    tshark_version = get_tshark_version()
    capinfos_version = get_capinfos_version()
    capinfos_row = read_capinfos_table(capture_path)

    direct_http2 = has_matching_frames(capture_path, "http2")
    forced_http2 = False
    if not direct_http2:
        forced_http2 = has_matching_frames(
            capture_path,
            "http2",
            decode_as=[HTTP2_DECODE_AS_RULE],
        )

    protocols = ProtocolPresence(
        ngap=has_matching_frames(capture_path, "ngap"),
        nas_5gs=has_matching_frames(capture_path, "nas-5gs"),
        http2=direct_http2 or forced_http2,
        http2_forced_on_7777=forced_http2,
        pfcp=has_matching_frames(capture_path, "pfcp"),
    )

    warnings: list[str] = []
    recommended_decode_as: list[str] = []

    if not is_minimum_version(tshark_version, MINIMUM_RECOMMENDED_TSHARK_VERSION):
        warnings.append(
            f"tshark {tshark_version} is below the recommended minimum {MINIMUM_RECOMMENDED_TSHARK_VERSION}"
        )
    if forced_http2 and not direct_http2:
        warnings.append("http2 was only detected after forcing decode-as on tcp.port==7777")
        recommended_decode_as.append(HTTP2_DECODE_AS_RULE)

    _, packet_count, file_size_bytes, duration_seconds, start_time_epoch, end_time_epoch = capinfos_row

    return CaptureInspection(
        path=str(capture_path),
        file_name=capture_path.name,
        file_size_bytes=int(file_size_bytes),
        packet_count=int(packet_count),
        duration_seconds=float(duration_seconds),
        start_time_epoch=float(start_time_epoch),
        end_time_epoch=float(end_time_epoch),
        protocols=protocols,
        recommended_decode_as=recommended_decode_as,
        warnings=warnings,
        tooling=ToolingInfo(
            tshark_version=tshark_version,
            capinfos_version=capinfos_version,
            tshark_minimum_recommended=MINIMUM_RECOMMENDED_TSHARK_VERSION,
            tshark_meets_minimum_recommended=is_minimum_version(
                tshark_version,
                MINIMUM_RECOMMENDED_TSHARK_VERSION,
            ),
        ),
    )
