from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Sequence

from traceweaver.core.tshark.runner import ExternalToolError

SUPPORTED_CAPTURE_SUFFIXES = {".pcap", ".pcapng"}


def validate_capture_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"capture file not found: {resolved}")
    if not resolved.is_file():
        raise IsADirectoryError(f"capture path is not a file: {resolved}")
    if resolved.suffix.lower() not in SUPPORTED_CAPTURE_SUFFIXES:
        raise ValueError(f"unsupported capture suffix: {resolved.suffix}")
    return resolved


def run_tshark_fields_extract(
    path: Path,
    *,
    display_filter: str | None,
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

    completed = subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise ExternalToolError(
            f"command failed: {' '.join(args)}\nstdout: {completed.stdout}\nstderr: {completed.stderr}"
        )
    return completed.stdout
