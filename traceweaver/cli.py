from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from traceweaver.core import AnalysisOptions, analyze_capture, list_profiles, list_scope_summaries
from traceweaver.tshark import ExternalToolError


def _add_output_args(parser: argparse.ArgumentParser) -> None:
    format_group = parser.add_mutually_exclusive_group()
    format_group.add_argument("--pretty", action="store_true")
    format_group.add_argument("--compact", action="store_true")


def _add_profile_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", type=str, default="open5gs_5gc")
    parser.add_argument("--display-filter", type=str, default=None)
    parser.add_argument("--decode-as", action="append", default=[])
    parser.add_argument("--limit", type=int)


def _add_llm_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="LLM model for diagnosis/investigation (e.g. ollama/qwen3:14b, gpt-4o). Omit to use rule-based diagnosis.",
    )
    parser.add_argument("--api-base", type=str, default=None, help="API base URL")
    parser.add_argument("--api-key", type=str, default=None, help="API key for OpenAI-compatible providers")
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")


def _build_options(args: argparse.Namespace) -> AnalysisOptions:
    return AnalysisOptions(
        display_filter=getattr(args, "display_filter", None),
        decode_as=list(getattr(args, "decode_as", []) or []),
        limit=getattr(args, "limit", None),
    )


def _build_llm_provider(args: argparse.Namespace):
    model = getattr(args, "model", None)
    if not model:
        return None

    from traceweaver.llm import LLMConfig, LLMProvider

    config = LLMConfig(
        model=model,
        api_base=getattr(args, "api_base", None),
        api_key=getattr(args, "api_key", None),
        temperature=getattr(args, "temperature", 0.1),
    )
    return LLMProvider(config)


def _emit_payload(payload, args: argparse.Namespace) -> None:
    indent = None if getattr(args, "compact", False) else 2
    print(payload.model_dump_json(indent=indent))


def main() -> None:
    parser = argparse.ArgumentParser(prog="traceweaver")
    subparsers = parser.add_subparsers(dest="command")

    profiles_parser = subparsers.add_parser("profiles")
    profiles_subparsers = profiles_parser.add_subparsers(dest="profiles_command")
    profiles_list_parser = profiles_subparsers.add_parser("list")
    _add_output_args(profiles_list_parser)

    scopes_parser = subparsers.add_parser("scopes")
    scopes_subparsers = scopes_parser.add_subparsers(dest="scopes_command")
    scopes_list_parser = scopes_subparsers.add_parser("list")
    scopes_list_parser.add_argument("pcap_path", type=Path)
    _add_profile_args(scopes_list_parser)
    _add_output_args(scopes_list_parser)

    analyze_parser = subparsers.add_parser("analyze")
    analyze_parser.add_argument("pcap_path", type=Path)
    _add_profile_args(analyze_parser)
    _add_llm_args(analyze_parser)
    _add_output_args(analyze_parser)

    diagnose_parser = subparsers.add_parser("diagnose")
    diagnose_parser.add_argument("pcap_path", type=Path)
    _add_profile_args(diagnose_parser)
    _add_llm_args(diagnose_parser)
    _add_output_args(diagnose_parser)

    investigate_parser = subparsers.add_parser("investigate")
    investigate_parser.add_argument("pcap_path", type=Path)
    _add_profile_args(investigate_parser)
    _add_llm_args(investigate_parser)
    _add_output_args(investigate_parser)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        raise SystemExit(1)

    if getattr(args, "verbose", False):
        logging.basicConfig(level=logging.DEBUG, format="%(name)s %(levelname)s: %(message)s", stream=sys.stderr)

    try:
        if args.command == "profiles":
            if args.profiles_command != "list":
                profiles_parser.print_help()
                raise SystemExit(1)
            payload = list_profiles()
        elif args.command == "scopes":
            if args.scopes_command != "list":
                scopes_parser.print_help()
                raise SystemExit(1)
            payload = list_scope_summaries(
                args.pcap_path,
                profile=args.profile,
                options=_build_options(args),
            )
        else:
            payload = analyze_capture(
                args.pcap_path,
                profile=args.profile,
                llm_provider=_build_llm_provider(args),
                options=_build_options(args),
            )
    except (ExternalToolError, FileNotFoundError, IsADirectoryError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc

    _emit_payload(payload, args)
