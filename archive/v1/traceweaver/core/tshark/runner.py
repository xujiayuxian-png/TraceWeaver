from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Sequence


class ExternalToolError(RuntimeError):
    pass


def run_checked(args: Sequence[str]) -> str:
    completed = subprocess.run(
        list(args),
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
    return completed.stdout.strip()


def _extract_semver(first_line: str, tool_name: str) -> str:
    match = re.search(r"(\d+\.\d+\.\d+)", first_line)
    if not match:
        raise ExternalToolError(f"cannot parse {tool_name} version from: {first_line}")
    return match.group(1)


def get_tshark_version() -> str:
    output = run_checked(["tshark", "--version"])
    return _extract_semver(output.splitlines()[0], "tshark")


def get_capinfos_version() -> str:
    output = run_checked(["capinfos", "--version"])
    return _extract_semver(output.splitlines()[0], "capinfos")


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def is_minimum_version(version: str, minimum: str) -> bool:
    return _version_tuple(version) >= _version_tuple(minimum)


def read_capinfos_table(path: Path) -> list[str]:
    output = run_checked(
        [
            "capinfos",
            "-M",
            "-c",
            "-s",
            "-u",
            "-a",
            "-e",
            "-S",
            str(path),
        ]
    )
    values: dict[str, str] = {}
    for line in output.splitlines():
        if ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        values[key.strip()] = raw_value.strip()

    start_time = values.get("First packet time") or values.get("Earliest packet time")
    end_time = values.get("Last packet time") or values.get("Latest packet time")

    try:
        return [
            values["File name"],
            values["Number of packets"],
            values["File size"].replace(" bytes", ""),
            values["Capture duration"].replace(" seconds", ""),
            start_time,
            end_time,
        ]
    except KeyError as exc:
        raise ExternalToolError(f"unexpected capinfos output: {output}") from exc


def has_matching_frames(
    path: Path,
    display_filter: str,
    decode_as: Sequence[str] | None = None,
) -> bool:
    args = ["tshark", "-r", str(path)]
    for rule in decode_as or []:
        args.extend(["-d", rule])
    args.extend(["-T", "fields", "-e", "frame.protocols"])
    output = run_checked(args)
    for line in output.splitlines():
        protocols = {token.strip().lower() for token in line.split(":") if token.strip()}
        if display_filter.lower() in protocols:
            return True
    return False
