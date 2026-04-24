"""
CLI tests for `traceweaver analyze`.

We do NOT spin up a real LLM. The Intelligence layer is patched to a
deterministic fake so we can assert the CLI glue (profile resolution,
source ingest, tool loading, output formatting) end-to-end.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from traceweaver.core.intelligence.base import (
    Intelligence,
    IntelligenceRequest,
    IntelligenceResponse,
)
from traceweaver.core.protocols import ToolCall
from traceweaver.core.source import Record


class _ScriptedIntelligence(Intelligence):
    """Intelligence that returns a pre-baked response sequence."""

    def __init__(self, responses: list[IntelligenceResponse]) -> None:
        self._responses = list(responses)
        self.calls = 0

    def think(self, request: IntelligenceRequest) -> IntelligenceResponse:
        resp = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        return resp


@pytest.fixture()
def fake_pcap_profile(tmp_path: Path) -> Path:
    root = tmp_path / "profiles" / "fake_demo"
    (root / "prompts").mkdir(parents=True)
    (root / "knowledge").mkdir()
    (root / "prompts" / "system.md").write_text("demo", encoding="utf-8")
    (root / "knowledge" / "k.md").write_text(
        "## Hello\nsome reference\n", encoding="utf-8"
    )
    (root / "profile.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "fake_demo",
                "llm": {"system_prompt_file": "prompts/system.md"},
                "knowledge": [{"file": "knowledge/k.md"}],
                "source_config": {"fake": {}},
                "tools": [],
                "enrichers": [],
            }
        ),
        encoding="utf-8",
    )
    return root


def _final_json(payload: dict[str, Any]) -> IntelligenceResponse:
    return IntelligenceResponse(
        kind="final",
        final_json=payload,
        final_text=json.dumps(payload),
        assistant_content=json.dumps(payload),
    )


def test_analyze_resolves_path_profile_and_runs(
    fake_pcap_profile: Path, monkeypatch, capsys
) -> None:
    # Patch LLMIntelligence in the CLI module to our fake.
    from traceweaver.cli import analyze as cli_mod

    monkeypatch.setattr(
        cli_mod,
        "LLMIntelligence",
        lambda **kw: _ScriptedIntelligence(
            [_final_json({"summary": "ok"})]
        ),
    )

    # Our profile's source_config has only "fake"; re-point --pcap to
    # go through the fake kind by stubbing _build_source_spec.
    def _spec(profile, args):
        from traceweaver.core.source import SourceSpec

        return SourceSpec(
            kind="fake",
            uri="memory://test",
            options={"records_object": [
                Record(source="fake", timestamp=1.0, seq=1, fields={"x": 1})
            ]},
        )

    monkeypatch.setattr(cli_mod, "_build_source_spec", _spec)

    from traceweaver.cli import main

    rc = main(
        [
            "analyze",
            "--profile",
            str(fake_pcap_profile),
            "--pcap",
            "dummy.pcap",
            "what is up",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert "stop_reason: final" in captured.out
    assert "summary" in captured.out


def test_analyze_missing_profile_returns_error(capsys) -> None:
    from traceweaver.cli import main

    rc = main(
        [
            "analyze",
            "--profile",
            "this_profile_does_not_exist_xyz",
            "--pcap",
            "nope.pcap",
            "q",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 2
    assert "error:" in captured.err


def test_analyze_requires_pcap_or_log(
    fake_pcap_profile: Path, monkeypatch, capsys
) -> None:
    from traceweaver.cli import main

    rc = main(
        [
            "analyze",
            "--profile",
            str(fake_pcap_profile),
            "q",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 2
    assert "--pcap" in captured.err or "--log" in captured.err


def test_json_output_mode(
    fake_pcap_profile: Path, monkeypatch, capsys
) -> None:
    from traceweaver.cli import analyze as cli_mod

    monkeypatch.setattr(
        cli_mod,
        "LLMIntelligence",
        lambda **kw: _ScriptedIntelligence(
            [_final_json({"verdict": "ok", "confidence": 0.9})]
        ),
    )

    def _spec(profile, args):
        from traceweaver.core.source import SourceSpec

        return SourceSpec(
            kind="fake",
            uri="memory://j",
            options={"records_object": [
                Record(source="fake", timestamp=1.0, seq=1, fields={})
            ]},
        )

    monkeypatch.setattr(cli_mod, "_build_source_spec", _spec)

    from traceweaver.cli import main

    rc = main(
        [
            "analyze",
            "--profile",
            str(fake_pcap_profile),
            "--pcap",
            "dummy.pcap",
            "--format",
            "json",
            "q",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    parsed = json.loads(out)
    assert parsed["stop_reason"] == "final"
    assert parsed["final_json"]["verdict"] == "ok"


def test_analyze_loads_profile_tools(tmp_path: Path, monkeypatch, capsys) -> None:
    from traceweaver.cli import analyze as cli_mod

    root = tmp_path / "profiles" / "with_tool"
    (root / "prompts").mkdir(parents=True)
    (root / "knowledge").mkdir()
    (root / "prompts" / "system.md").write_text("demo", encoding="utf-8")
    (root / "knowledge" / "k.md").write_text("x", encoding="utf-8")
    tools_dir = root / "tools"
    tools_dir.mkdir()
    (tools_dir / "__init__.py").write_text("", encoding="utf-8")
    (tools_dir / "echo_tool.py").write_text(
        "\n".join(
            [
                "from traceweaver.core.protocols import Tool, ToolContext, ToolResult, ToolSpec",
                "",
                "class LocalEchoTool(Tool):",
                "    spec = ToolSpec(",
                "        name='local_echo',",
                "        description='local test tool',",
                "        parameters_schema={",
                "            'type': 'object',",
                "            'properties': {'text': {'type': 'string'}},",
                "            'required': ['text'],",
                "        },",
                "    )",
                "",
                "    def run(self, ctx: ToolContext, **kwargs):",
                "        return ToolResult(data={'echo': kwargs.get('text', '')})",
            ]
        ),
        encoding="utf-8",
    )
    (root / "profile.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "with_tool",
                "llm": {"system_prompt_file": "prompts/system.md"},
                "knowledge": [{"file": "knowledge/k.md"}],
                "source_config": {"fake": {}},
                "tools": [
                    {
                        "module": "with_tool.tools.echo_tool",
                        "class": "LocalEchoTool",
                    }
                ],
                "enrichers": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(root.parent))

    monkeypatch.setattr(
        cli_mod,
        "LLMIntelligence",
        lambda **kw: _ScriptedIntelligence(
            [
                IntelligenceResponse(
                    kind="tool_calls",
                    assistant_content="need local tool",
                    tool_calls=[
                        ToolCall(
                            id="call_1",
                            name="local_echo",
                            arguments={"text": "ok"},
                        )
                    ],
                ),
                _final_json({"summary": "done"}),
            ]
        ),
    )

    def _spec(profile, args):
        from traceweaver.core.source import SourceSpec

        return SourceSpec(
            kind="fake",
            uri="memory://local-tool",
            options={"records_object": [Record(source="fake", timestamp=1.0, seq=1, fields={})]},
        )

    monkeypatch.setattr(cli_mod, "_build_source_spec", _spec)

    from traceweaver.cli import main

    rc = main(
        [
            "analyze",
            "--profile",
            str(root),
            "--pcap",
            "dummy.pcap",
            "--format",
            "json",
            "q",
        ]
    )
    parsed = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert parsed["stop_reason"] == "final"
    assert parsed["tool_calls_total"] == 1
