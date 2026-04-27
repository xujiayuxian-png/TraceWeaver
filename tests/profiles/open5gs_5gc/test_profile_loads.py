"""Verify the built-in 5GC profile loads end-to-end (yaml + tools + enrichers)."""

from __future__ import annotations

from traceweaver.core.profile.runtime import resolve_enrichers
from traceweaver.core.tools.loader import load_profile_tools
from traceweaver.core.tools.registry import ToolRegistry


def test_profile_loads_with_expected_shape(profile) -> None:
    assert profile.name == "open5gs_5gc"
    assert "pcap" in profile.source_config
    assert profile.llm.system_prompt.strip().startswith(
        "# TraceWeaver: Open5GS 5GC diagnosis agent"
    )
    assert profile.llm.response_schema is not None
    assert "verdict" in profile.llm.response_schema.get("required", [])


def test_enrichers_import(profile) -> None:
    fns = resolve_enrichers(profile.enrichers)
    assert len(fns) == 1
    # Must be callable and deterministic.
    from traceweaver.profiles.open5gs_5gc.enrich import enrich as direct

    assert fns[0] is direct


def test_all_declared_tools_load(profile) -> None:
    reg = ToolRegistry()
    names = load_profile_tools(reg, profile.tools)
    assert set(names) == {
        "summarize_capture",
        "list_ue_sessions",
        "get_ue_timeline",
        "get_sbi_calls",
        "get_pfcp_exchanges",
        "get_nas_cause_meaning",
    }
    assert names[0] == "summarize_capture"


def test_prompt_required_tools_are_declared(profile) -> None:
    reg = ToolRegistry()
    names = set(load_profile_tools(reg, profile.tools))
    prompt = profile.llm.system_prompt
    assert "summarize_capture" in prompt
    assert "summarize_capture" in names
    workflow_section = prompt.split("## Workflow", 1)[-1].split("##", 1)[0]
    assert "summarize_capture" in workflow_section


def test_prompt_uses_hard_m3_contract_only(profile) -> None:
    assert "likely_" not in profile.llm.system_prompt
    assert "capture_findings" not in profile.llm.system_prompt
    assert "verdict_guardrails" not in profile.llm.system_prompt


def test_knowledge_files_exist(profile) -> None:
    for item in profile.knowledge:
        assert item.path.is_file(), f"missing: {item.path}"
