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
        "list_ue_sessions",
        "get_ue_timeline",
        "get_sbi_calls",
        "get_pfcp_exchanges",
        "get_nas_cause_meaning",
    }


def test_knowledge_files_exist(profile) -> None:
    for item in profile.knowledge:
        assert item.path.is_file(), f"missing: {item.path}"
