"""Tests for the `traceweaver profile list` subcommand."""

from __future__ import annotations

import json

import pytest

from traceweaver.cli import main


def _run_cli(capsys, args: list[str]) -> tuple[int, str, str]:
    rc = main(args)
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def test_profile_list_text_includes_builtin(capsys) -> None:
    rc, out, _ = _run_cli(capsys, ["profile", "list"])
    assert rc == 0
    assert "open5gs_5gc" in out
    assert "builtin" in out


def test_profile_list_json(capsys) -> None:
    rc, out, _ = _run_cli(capsys, ["profile", "list", "--format", "json"])
    assert rc == 0
    payload = json.loads(out)
    by_name = {entry["name"]: entry for entry in payload}
    assert "open5gs_5gc" in by_name
    assert by_name["open5gs_5gc"]["origin"] == "builtin"
    assert by_name["open5gs_5gc"]["path"].endswith("open5gs_5gc")


def test_profile_list_requires_action(capsys) -> None:
    """Bare `traceweaver profile` must error out (no default action)."""
    with pytest.raises(SystemExit) as excinfo:
        main(["profile"])
    assert excinfo.value.code != 0
