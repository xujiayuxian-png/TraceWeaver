"""
PcapSource: wraps `tshark` to ingest a .pcap/.pcapng into `Record`s.

M2 scope is deliberately minimal:

- One subprocess call per ingest (no on-demand re-shelling for new fields).
- Fields the caller asks for PLUS two universal ones (frame.number,
  frame.time_epoch) are extracted via `-T fields -E header=y`.
- `display_filter` narrows the capture at read time.
- `key_strategy` decides how to compute `Record.key`:
    * `{mode: "derived_fields", fields: [a, b, ...]}` -> join non-empty
      values of those fields with "|" (fields must be in options.fields)
    * `{mode: "field", field: "tcp.stream"}` -> use that single field
    * omitted / unknown -> ""

Error behavior: if `tshark` is missing, `ingest` raises FileNotFoundError
with a clear message. Profiles that depend on pcap can surface this to
the CLI layer later.

Tests cover the parsing path via a `tshark_runner` injection point.
"""

from __future__ import annotations

import shutil
import subprocess
from bisect import bisect_left
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence

from traceweaver.core.source.base import Record, Source, SourceHandle, SourceSpec


# Fields we always request from tshark; anything else comes from
# `options.fields`. Keeping the universal two at the front makes
# parsing easier.
_UNIVERSAL_FIELDS: tuple[str, ...] = ("frame.number", "frame.time_epoch")


# A tshark runner returns the stdout of a tshark invocation. Injected
# for testing; production uses `_default_tshark_runner`.
TsharkRunner = Callable[[Sequence[str]], str]


def _default_tshark_runner(argv: Sequence[str]) -> str:
    exe = shutil.which(argv[0])
    if exe is None:
        raise FileNotFoundError(
            f"{argv[0]!r} not found in PATH; install wireshark/tshark first"
        )
    full = [exe, *argv[1:]]
    completed = subprocess.run(  # noqa: S603 - argv is caller-controlled
        full,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"tshark exited with {completed.returncode}: "
            f"{completed.stderr.strip()[:500]}"
        )
    return completed.stdout


def _match(record: Record, flt: dict[str, Any]) -> bool:
    for key, want in flt.items():
        got: Any
        if key in {"source", "timestamp", "seq", "key", "raw"}:
            got = getattr(record, key)
        else:
            got = record.fields.get(key)
        if got != want:
            return False
    return True


def _project(record: Record, fields: list[str] | None) -> Record:
    if fields is None:
        return record
    keep = {k: v for k, v in record.fields.items() if k in set(fields)}
    return record.model_copy(update={"fields": keep})


def _compute_key(fields: dict[str, Any], strategy: dict[str, Any] | None) -> str:
    if not strategy:
        return ""
    mode = strategy.get("mode")
    if mode == "derived_fields":
        parts = []
        for name in strategy.get("fields", []):
            val = fields.get(name)
            if val is None or val == "":
                continue
            parts.append(str(val))
        return "|".join(parts)
    if mode == "field":
        val = fields.get(strategy.get("field", ""))
        return "" if val is None else str(val)
    return ""


def parse_tshark_fields_output(
    text: str,
    *,
    extra_fields: Sequence[str] | None = None,
    separator: str = "\t",
    key_strategy: dict[str, Any] | None = None,
    max_records: int | None = None,
    time_range: tuple[float, float] | None = None,
) -> list[Record]:
    """
    Parse tshark -T fields output into Records.

    Parameters
    ----------
    extra_fields:
        Field names that appear after the universal columns in each line.
    separator:
        The field separator used in tshark output (must match -E separator=).
    key_strategy:
        Optional dict with mode/fields for computing Record.key.
    max_records:
        Maximum number of records to return (None = unlimited).
    time_range:
        Relative time window [start_s, end_s] from first frame (None = unlimited).

    Returns
    -------
    List of Record objects sorted by seq (frame.number).
    """
    lines = [ln for ln in text.splitlines() if ln != ""]
    if not lines:
        return []
    header = lines[0].split(separator)
    if header[: len(_UNIVERSAL_FIELDS)] != list(_UNIVERSAL_FIELDS):
        raise ValueError(
            "tshark header missing universal fields; "
            f"got {header[: len(_UNIVERSAL_FIELDS)]!r}"
        )
    records: list[Record] = []
    first_ts: float | None = None
    emitted = 0
    for line in lines[1:]:
        # max_records limit check
        if max_records is not None and emitted >= max_records:
            break
        cols = line.split(separator)
        # Pad short rows (tshark drops trailing empty fields sometimes).
        if len(cols) < len(header):
            cols = cols + [""] * (len(header) - len(cols))
        try:
            seq = int(cols[0])
            ts = float(cols[1])
        except ValueError:
            # Junk row (e.g. a stderr blob that slipped in). Skip it.
            continue
        # time_range filter (relative to first frame)
        if time_range is not None:
            if first_ts is None:
                first_ts = ts
            rel_ts = ts - first_ts
            start_s, end_s = time_range
            if rel_ts < start_s or rel_ts > end_s:
                continue
        field_map: dict[str, Any] = {}
        for name, val in zip(header[len(_UNIVERSAL_FIELDS) :], cols[len(_UNIVERSAL_FIELDS) :]):
            field_map[name] = val
        # Keep the universal fields available under their tshark names too,
        # so tool filters like {"frame.number": 42} work uniformly.
        field_map["frame.number"] = seq
        field_map["frame.time_epoch"] = ts
        key = _compute_key(field_map, key_strategy)
        records.append(
            Record(
                source="pcap",
                timestamp=ts,
                seq=seq,
                key=key,
                fields={k: v for k, v in field_map.items() if k in set(extra_fields) | set(_UNIVERSAL_FIELDS)},
                raw=line,
            )
        )
        emitted += 1
    return records


class PcapSourceHandle(SourceHandle):
    kind = "pcap"

    def __init__(self, uri: str, records: list[Record]) -> None:
        self.uri = uri
        self._records: list[Record] = sorted(records, key=lambda r: r.seq)
        self._seqs: list[int] = [r.seq for r in self._records]

    def metadata(self) -> dict[str, Any]:
        if not self._records:
            return {"count": 0, "time_range": None}
        return {
            "count": len(self._records),
            "time_range": [
                self._records[0].timestamp,
                self._records[-1].timestamp,
            ],
            "seq_range": [self._records[0].seq, self._records[-1].seq],
        }

    def iter_records(
        self,
        *,
        filter: dict[str, Any] | None = None,
        fields: list[str] | None = None,
        limit: int | None = None,
    ) -> Iterator[Record]:
        emitted = 0
        for r in self._records:
            if filter and not _match(r, filter):
                continue
            yield _project(r, fields)
            emitted += 1
            if limit is not None and emitted >= limit:
                return

    def get_records_around(
        self, seq: int, *, before: int = 2, after: int = 2
    ) -> list[Record]:
        if not self._records:
            return []
        idx = bisect_left(self._seqs, seq)
        lo = max(0, idx - before)
        hi = min(len(self._records), idx + after + 1)
        return list(self._records[lo:hi])


class PcapSource(Source):
    kind = "pcap"

    def __init__(self, tshark_runner: TsharkRunner | None = None) -> None:
        self._run = tshark_runner or _default_tshark_runner

    def ingest(self, spec: SourceSpec) -> SourceHandle:
        if spec.kind != self.kind:
            raise ValueError(
                f"PcapSource cannot ingest kind={spec.kind!r} (expected 'pcap')"
            )
        uri = spec.uri
        opts = spec.options
        extra_fields: list[str] = list(opts.get("fields", []))
        display_filter: str | None = opts.get("display_filter")
        decode_as: list[str] = list(opts.get("decode_as", []))
        key_strategy: dict[str, Any] | None = opts.get("key_strategy")
        separator = opts.get("field_separator", "\t")
        # P1.3: slicing options for large pcaps
        max_records: int | None = opts.get("max_records")
        time_range: tuple[float, float] | None = opts.get("time_range")

        # Existence check is advisory; the runner may be a fake that
        # doesn't care about filesystem presence (tests).
        if self._run is _default_tshark_runner and not Path(uri).exists():
            raise FileNotFoundError(f"pcap not found: {uri}")

        argv: list[str] = [
            "tshark",
            "-r", uri,
            "-n",
            "-T", "fields",
            "-E", "header=y",
            "-E", f"separator={separator}",
            "-E", "occurrence=f",
        ]
        if display_filter:
            argv += ["-Y", display_filter]
        for da in decode_as:
            argv += ["-d", da]
        for f in _UNIVERSAL_FIELDS:
            argv += ["-e", f]
        seen: set[str] = set(_UNIVERSAL_FIELDS)
        for f in extra_fields:
            if f in seen:
                continue
            seen.add(f)
            argv += ["-e", f]

        stdout = self._run(argv)
        records = parse_tshark_fields_output(
            stdout,
            extra_fields=list(seen),
            separator=separator,
            key_strategy=key_strategy,
            max_records=max_records,
            time_range=time_range,
        )
        return PcapSourceHandle(uri=uri, records=records)


__all__ = [
    "PcapSource",
    "PcapSourceHandle",
    "TsharkRunner",
    "parse_tshark_fields_output",
]
