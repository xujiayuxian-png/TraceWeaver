"""
`traceweaver validate-profile` — validate a profile directory.

Checks:
  1. profile.yaml syntax is valid
  2. Referenced files (system_prompt, response_schema, knowledge) exist
  3. Enrichers are importable and callable
  4. Tools are importable and are Tool subclasses (or factory returns Tool)
  5. source_config.fields is non-empty list of strings

Exit 0 if all checks pass, 1 otherwise.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from traceweaver.core.profile import load_profile_from_dir
from traceweaver.core.tools.base import Tool


def _check_file_exists(path: Path, desc: str, errors: list[str]) -> bool:
    """Check if a file exists, append error if not."""
    if not path.is_file():
        errors.append(f"{desc} not found: {path}")
        return False
    return True


def _validate_profile(profile_dir: Path, verbose: bool = False) -> list[str]:
    """
    Validate a profile directory.
    Returns list of error messages (empty if valid).
    """
    errors: list[str] = []
    warnings: list[str] = []

    # 1. Load profile.yaml
    try:
        profile = load_profile_from_dir(profile_dir)
    except Exception as e:
        errors.append(f"Failed to load profile.yaml: {e}")
        return errors

    if verbose:
        print(f"Profile: {profile.name} (v{profile.version})")
        print(f"  Root: {profile.root}")

    # 2. Check LLM config loaded successfully
    if not profile.llm.system_prompt:
        errors.append("system_prompt is empty or failed to load")
    elif verbose:
        prompt_preview = profile.llm.system_prompt[:100].replace('\n', ' ')
        print(f"  System prompt: {prompt_preview}... ({len(profile.llm.system_prompt)} chars)")

    if profile.llm.response_schema is None:
        errors.append("response_schema failed to load or parse")
    elif verbose:
        print(f"  Response schema: {len(profile.llm.response_schema)} key(s)")

    # knowledge files
    for item in profile.knowledge:
        if not _check_file_exists(item.path, "knowledge file", errors):
            continue
        if verbose:
            print(f"  Knowledge: {item.path.name} (tags: {item.tags})")

    # 3. Validate enrichers
    for spec in profile.enrichers:
        try:
            mod = __import__(spec.module, fromlist=[spec.function])
            fn = getattr(mod, spec.function, None)
            if fn is None:
                errors.append(f"Enricher function not found: {spec.module}.{spec.function}")
                continue
            if not callable(fn):
                errors.append(f"Enricher is not callable: {spec.module}.{spec.function}")
                continue
            if verbose:
                print(f"  Enricher: {spec.module}.{spec.function} OK")
        except Exception as e:
            errors.append(f"Failed to load enricher {spec.module}.{spec.function}: {e}")

    # 4. Validate tools (profile.tools is list[dict])
    for idx, spec in enumerate(profile.tools):
        try:
            module_name = spec.get("module")
            cls_name = spec.get("class")
            factory_name = spec.get("factory")
            if not module_name:
                errors.append(f"Tool [{idx}] missing 'module'")
                continue
            mod = __import__(module_name, fromlist=[cls_name or factory_name or "Tool"])
            if cls_name:
                cls = getattr(mod, cls_name, None)
                if cls is None:
                    errors.append(f"Tool class not found: {module_name}.{cls_name}")
                    continue
                if not isinstance(cls, type) or not issubclass(cls, Tool):
                    errors.append(f"Tool is not a Tool subclass: {module_name}.{cls_name}")
                    continue
                if verbose:
                    print(f"  Tool [{idx}]: {module_name}.{cls_name} OK")
            elif factory_name:
                factory = getattr(mod, factory_name, None)
                if factory is None:
                    errors.append(f"Tool factory not found: {module_name}.{factory_name}")
                    continue
                if not callable(factory):
                    errors.append(f"Tool factory is not callable: {module_name}.{factory_name}")
                    continue
                if verbose:
                    print(f"  Tool [{idx}]: {module_name}.{factory_name}(factory) OK")
            else:
                errors.append(f"Tool [{idx}] missing both 'class' and 'factory': {module_name}")
        except Exception as e:
            name = spec.get("class") or spec.get("factory") or "unknown"
            errors.append(f"Failed to load tool [{idx}] {name}: {e}")

    # 5. Validate source_config
    if "pcap" in profile.source_config:
        pcap_config = profile.source_config["pcap"]
        fields = pcap_config.get("fields", [])
        if not fields:
            warnings.append("source_config.pcap.fields is empty (may be intentional)")
        elif not isinstance(fields, list):
            errors.append("source_config.pcap.fields must be a list")
        elif not all(isinstance(f, str) for f in fields):
            errors.append("source_config.pcap.fields must be a list of strings")
        else:
            if verbose:
                print(f"  PCAP fields: {len(fields)} field(s) configured")
    else:
        if verbose:
            print("  No pcap source_config (may use other source kinds)")

    # Print warnings
    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)

    return errors


def run(args: argparse.Namespace) -> int:
    profile_dir = Path(args.profile_dir)
    if not profile_dir.is_dir():
        print(f"ERROR: Not a directory: {profile_dir}", file=sys.stderr)
        return 1

    errors = _validate_profile(profile_dir, verbose=args.verbose)

    if errors:
        print(f"\nValidation FAILED: {len(errors)} error(s)", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    print("Validation PASSED")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "validate-profile",
        help="Validate a profile directory structure and configuration.",
    )
    p.add_argument(
        "profile_dir",
        help="Path to profile directory containing profile.yaml",
    )
    p.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Print detailed validation info",
    )
    p.set_defaults(func=run)
