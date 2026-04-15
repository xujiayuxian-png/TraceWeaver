from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from traceweaver.diagnosis import run_diagnosis
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

    diag_parser = subparsers.add_parser("diagnose")
    diag_parser.add_argument("pcap_path", type=Path)
    diag_parser.add_argument("--limit", type=int)
    diag_parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="LLM model for diagnosis (e.g. ollama/qwen2.5:14b, gpt-4o, openai/gpt-4.1-mini). "
             "Omit to use the rule engine.",
    )
    diag_parser.add_argument("--api-base", type=str, default=None, help="API base URL (e.g. http://localhost:11434)")
    diag_parser.add_argument("--api-key", type=str, default=None, help="API key for OpenAI-compatible providers")
    diag_parser.add_argument("--temperature", type=float, default=0.1)
    diag_parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    diag_format_group = diag_parser.add_mutually_exclusive_group()
    diag_format_group.add_argument("--pretty", action="store_true")
    diag_format_group.add_argument("--compact", action="store_true")

    args = parser.parse_args()

    valid_commands = {
        "inspect-pcap", "extract-records", "extract-events",
        "extract-sessions", "extract-sbi", "extract-pdu-sessions", "diagnose",
    }
    if args.command not in valid_commands:
        parser.print_help()
        raise SystemExit(1)

    if getattr(args, "verbose", False):
        logging.basicConfig(level=logging.DEBUG, format="%(name)s %(levelname)s: %(message)s", stream=sys.stderr)

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
        elif args.command == "diagnose":
            llm_provider = None
            if args.model:
                from traceweaver.llm import LLMConfig, LLMProvider
                config = LLMConfig(
                    model=args.model,
                    api_base=args.api_base,
                    api_key=args.api_key,
                    temperature=args.temperature,
                )
                llm_provider = LLMProvider(config)
            payload = run_diagnosis(args.pcap_path, limit=args.limit, llm_provider=llm_provider)
        else:
            payload = extract_ue_sessions(args.pcap_path, limit=args.limit)
    except (ExternalToolError, FileNotFoundError, IsADirectoryError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc

    indent = None if getattr(args, "compact", False) else 2
    print(payload.model_dump_json(indent=indent))
