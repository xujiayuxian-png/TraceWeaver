from __future__ import annotations

import argparse
import sys
from pathlib import Path

from traceweaver.ingest import extract_5gc_events, extract_pdu_sessions, extract_5gc_records, extract_sbi_calls, extract_ue_sessions, inspect_capture
from traceweaver.tshark import ExternalToolError


def main() -> None:
    parser = argparse.ArgumentParser(prog="traceweaver")
    subparsers = parser.add_subparsers(dest="command")

    inspect_parser = subparsers.add_parser("inspect-pcap")
    inspect_parser.add_argument("pcap_path", type=Path)
    format_group = inspect_parser.add_mutually_exclusive_group()
    format_group.add_argument("--pretty", action="store_true")
    format_group.add_argument("--compact", action="store_true")

    extract_parser = subparsers.add_parser("extract-records")
    extract_parser.add_argument("pcap_path", type=Path)
    extract_parser.add_argument("--limit", type=int)
    extract_format_group = extract_parser.add_mutually_exclusive_group()
    extract_format_group.add_argument("--pretty", action="store_true")
    extract_format_group.add_argument("--compact", action="store_true")

    events_parser = subparsers.add_parser("extract-events")
    events_parser.add_argument("pcap_path", type=Path)
    events_parser.add_argument("--limit", type=int)
    events_format_group = events_parser.add_mutually_exclusive_group()
    events_format_group.add_argument("--pretty", action="store_true")
    events_format_group.add_argument("--compact", action="store_true")

    sessions_parser = subparsers.add_parser("extract-sessions")
    sessions_parser.add_argument("pcap_path", type=Path)
    sessions_parser.add_argument("--limit", type=int)
    sessions_format_group = sessions_parser.add_mutually_exclusive_group()
    sessions_format_group.add_argument("--pretty", action="store_true")
    sessions_format_group.add_argument("--compact", action="store_true")

    sbi_parser = subparsers.add_parser("extract-sbi")
    sbi_parser.add_argument("pcap_path", type=Path)
    sbi_parser.add_argument("--limit", type=int)
    sbi_format_group = sbi_parser.add_mutually_exclusive_group()
    sbi_format_group.add_argument("--pretty", action="store_true")
    sbi_format_group.add_argument("--compact", action="store_true")

    pdu_parser = subparsers.add_parser("extract-pdu-sessions")
    pdu_parser.add_argument("pcap_path", type=Path)
    pdu_parser.add_argument("--limit", type=int)
    pdu_format_group = pdu_parser.add_mutually_exclusive_group()
    pdu_format_group.add_argument("--pretty", action="store_true")
    pdu_format_group.add_argument("--compact", action="store_true")

    args = parser.parse_args()

    if args.command not in {"inspect-pcap", "extract-records", "extract-events", "extract-sessions", "extract-sbi", "extract-pdu-sessions"}:
        parser.print_help()
        raise SystemExit(1)

    try:
        if args.command == "inspect-pcap":
            payload = inspect_capture(args.pcap_path)
        elif args.command == "extract-records":
            payload = extract_5gc_records(args.pcap_path, limit=args.limit)
        elif args.command == "extract-events":
            payload = extract_5gc_events(args.pcap_path, limit=args.limit)
        elif args.command == "extract-sbi":
            payload = extract_sbi_calls(args.pcap_path, limit=args.limit)
        elif args.command == "extract-pdu-sessions":
            payload = extract_pdu_sessions(args.pcap_path, limit=args.limit)
        else:
            payload = extract_ue_sessions(args.pcap_path, limit=args.limit)
    except (ExternalToolError, FileNotFoundError, IsADirectoryError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc

    indent = None if args.compact else 2
    print(payload.model_dump_json(indent=indent))
