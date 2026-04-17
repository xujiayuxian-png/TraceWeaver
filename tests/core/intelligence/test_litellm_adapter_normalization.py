"""
Offline tests for LLMIntelligence response normalization.

These tests never touch the network. They poke the adapter's
response-parsing path directly with hand-built provider responses, so
we can pin behaviour for:

  1. Structured OpenAI tool_calls (the happy path)
  2. Qwen native tool-call JSON leaking into content
  3. Qwen native tool-call XML leaking into reasoning_content
  4. Final plain-text answer
  5. Final answer where the JSON object lives in reasoning_content only
  6. Multiple leaked tool calls in one turn
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from traceweaver.core.intelligence.base import IntelligenceRequest
from traceweaver.core.intelligence.litellm_adapter import (
    LLMIntelligence,
    extract_leaked_tool_calls,
)
from traceweaver.core.types import Message


TOOLS_SPEC = [
    {
        "type": "function",
        "function": {
            "name": "get_frame_at",
            "description": "Look up a frame by number.",
            "parameters": {
                "type": "object",
                "properties": {
                    "frame_number": {"type": "integer"},
                },
                "required": ["frame_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": "Search the 3GPP knowledge base.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                },
                "required": ["query"],
            },
        },
    },
]


def _fake_completion(
    *,
    content: str | None = "",
    reasoning: str | None = None,
    tool_calls: list[dict] | None = None,
):
    """Build a duck-typed litellm response."""
    msg = SimpleNamespace(
        content=content,
        reasoning_content=reasoning,
        tool_calls=[
            SimpleNamespace(
                id=tc.get("id"),
                function=SimpleNamespace(
                    name=tc["name"],
                    arguments=tc.get("arguments", "{}"),
                ),
            )
            for tc in (tool_calls or [])
        ]
        or None,
    )
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def _make_adapter() -> LLMIntelligence:
    return LLMIntelligence(model="openai/fake-model")


def _req(tools=TOOLS_SPEC, response_schema=None) -> IntelligenceRequest:
    return IntelligenceRequest(
        system_prompt="sys",
        messages=[Message(role="user", content="hi")],
        tools=tools,
        response_schema=response_schema,
    )


# ---- happy path: structured tool_calls ------------------------------------


def test_structured_tool_calls_pass_through():
    adapter = _make_adapter()
    resp = _fake_completion(
        tool_calls=[
            {
                "id": "call-1",
                "name": "get_frame_at",
                "arguments": '{"frame_number": 42}',
            }
        ]
    )
    result = adapter._parse_completion(resp, _req())

    assert result.kind == "tool_calls"
    assert len(result.tool_calls) == 1
    tc = result.tool_calls[0]
    assert tc.id == "call-1"
    assert tc.name == "get_frame_at"
    assert tc.arguments == {"frame_number": 42}


def test_structured_tool_call_with_dict_arguments():
    """Some providers already hand us a dict rather than a JSON string."""
    adapter = _make_adapter()
    resp = _fake_completion(
        tool_calls=[
            {
                "id": "call-x",
                "name": "search_knowledge",
                "arguments": {"query": "cause 20"},
            }
        ]
    )
    result = adapter._parse_completion(resp, _req())

    assert result.kind == "tool_calls"
    assert result.tool_calls[0].arguments == {"query": "cause 20"}


def test_structured_tool_call_missing_id_gets_synthetic_id():
    adapter = _make_adapter()
    resp = _fake_completion(
        tool_calls=[{"id": None, "name": "get_frame_at", "arguments": "{}"}]
    )
    result = adapter._parse_completion(resp, _req())

    assert result.tool_calls[0].id.startswith("call-")


# ---- Qwen native leak recovery --------------------------------------------


def test_qwen_json_form_in_content_is_recovered():
    adapter = _make_adapter()
    content = (
        'Here is my plan:\n<tool_call>{"name": "get_frame_at", '
        '"arguments": {"frame_number": 42}}</tool_call>\n'
    )
    resp = _fake_completion(content=content, tool_calls=None)
    result = adapter._parse_completion(resp, _req())

    assert result.kind == "tool_calls"
    assert len(result.tool_calls) == 1
    tc = result.tool_calls[0]
    assert tc.name == "get_frame_at"
    assert tc.arguments == {"frame_number": 42}
    assert tc.id.startswith("extracted-")


def test_qwen_xml_form_in_reasoning_is_recovered_with_type_coercion():
    adapter = _make_adapter()
    reasoning = (
        "I need to look up frame 42.\n"
        "<tool_call>\n"
        "<function=get_frame_at>\n"
        "<parameter=frame_number>\n"
        "42\n"
        "</parameter>\n"
        "</function>\n"
        "</tool_call>"
    )
    resp = _fake_completion(content="", reasoning=reasoning, tool_calls=None)
    result = adapter._parse_completion(resp, _req())

    assert result.kind == "tool_calls"
    assert len(result.tool_calls) == 1
    tc = result.tool_calls[0]
    assert tc.name == "get_frame_at"
    assert tc.arguments == {"frame_number": 42}
    assert isinstance(tc.arguments["frame_number"], int)
    assert result.reasoning == reasoning


def test_multiple_xml_tool_calls_in_one_turn():
    adapter = _make_adapter()
    reasoning = (
        "<tool_call><function=search_knowledge>"
        "<parameter=query>alpha</parameter></function></tool_call>\n"
        "<tool_call><function=search_knowledge>"
        "<parameter=query>beta</parameter></function></tool_call>"
    )
    resp = _fake_completion(content=None, reasoning=reasoning, tool_calls=None)
    result = adapter._parse_completion(resp, _req())

    assert result.kind == "tool_calls"
    assert [tc.name for tc in result.tool_calls] == [
        "search_knowledge",
        "search_knowledge",
    ]
    assert [tc.arguments["query"] for tc in result.tool_calls] == ["alpha", "beta"]


def test_content_precedence_over_reasoning_on_leak():
    """If a leak is in both content and reasoning, content wins."""
    adapter = _make_adapter()
    content = (
        "<tool_call><function=search_knowledge>"
        "<parameter=query>from-content</parameter></function></tool_call>"
    )
    reasoning = (
        "<tool_call><function=search_knowledge>"
        "<parameter=query>from-reasoning</parameter></function></tool_call>"
    )
    resp = _fake_completion(content=content, reasoning=reasoning, tool_calls=None)
    result = adapter._parse_completion(resp, _req())

    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].arguments == {"query": "from-content"}


def test_native_tool_calls_win_over_leak():
    """If the provider DID give us structured tool_calls, ignore any leak."""
    adapter = _make_adapter()
    leak_content = (
        "<tool_call><function=search_knowledge>"
        "<parameter=query>ignored</parameter></function></tool_call>"
    )
    resp = _fake_completion(
        content=leak_content,
        tool_calls=[
            {
                "id": "c1",
                "name": "get_frame_at",
                "arguments": '{"frame_number": 7}',
            }
        ],
    )
    result = adapter._parse_completion(resp, _req())

    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "get_frame_at"
    assert result.tool_calls[0].arguments == {"frame_number": 7}


# ---- final answer path ----------------------------------------------------


def test_plain_text_final_answer():
    adapter = _make_adapter()
    resp = _fake_completion(content="There are 2 sessions.", tool_calls=None)
    result = adapter._parse_completion(resp, _req())

    assert result.kind == "final"
    assert result.final_text == "There are 2 sessions."
    assert result.final_json is None


def test_final_json_extracted_when_schema_requested():
    adapter = _make_adapter()
    schema = {
        "type": "object",
        "properties": {"verdict": {"type": "string"}},
        "required": ["verdict"],
    }
    resp = _fake_completion(
        content='The verdict:\n{"verdict": "FAIL", "reason": "MAC mismatch"}\n',
        tool_calls=None,
    )
    result = adapter._parse_completion(resp, _req(response_schema=schema))

    assert result.kind == "final"
    assert result.final_json == {"verdict": "FAIL", "reason": "MAC mismatch"}


def test_final_json_falls_back_to_reasoning_content():
    """Some LM Studio builds put the final object in reasoning_content only."""
    adapter = _make_adapter()
    schema = {
        "type": "object",
        "properties": {"verdict": {"type": "string"}},
        "required": ["verdict"],
    }
    resp = _fake_completion(
        content="",
        reasoning='Let me think...\n{"verdict": "OK"}',
        tool_calls=None,
    )
    result = adapter._parse_completion(resp, _req(response_schema=schema))

    assert result.kind == "final"
    assert result.final_json == {"verdict": "OK"}


def test_no_leak_no_spurious_extraction():
    """A final turn with normal prose and no <tool_call> tag stays final."""
    adapter = _make_adapter()
    resp = _fake_completion(
        content="I found 2 sessions in the capture.", tool_calls=None
    )
    result = adapter._parse_completion(resp, _req())

    assert result.kind == "final"
    assert result.tool_calls == []


# ---- the standalone extractor (used directly in tight-loop tests) ---------


@pytest.mark.parametrize("text", ["", None, "no tags here", "<tool_call></tool_call>"])
def test_extract_leaked_tool_calls_nothing_to_do(text):
    assert extract_leaked_tool_calls(text, TOOLS_SPEC) == []


def test_extract_leaked_tool_calls_json_shape():
    text = '<tool_call>{"name": "get_frame_at", "arguments": "{\\"frame_number\\": 9}"}</tool_call>'
    got = extract_leaked_tool_calls(text, TOOLS_SPEC)
    assert got == [{"name": "get_frame_at", "arguments": {"frame_number": 9}}]
