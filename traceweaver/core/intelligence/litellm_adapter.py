"""
LLMIntelligence: litellm-backed implementation of Intelligence.

This is the one place in TraceWeaver that actually talks HTTP to a chat
model provider, and it is therefore the one place that knows about
provider quirks. Everything upstream (kernel, tools, CLI) only sees
the neutral `IntelligenceResponse` shape.

Known quirks absorbed here (see `M1-handover/tool-calling-runbook.md`
for the full story; M1 baseline is LM Studio + `qwen/qwen3.5-9b`):

- ollama + qwen3 family:
    Thinking mode is on by default and bleeds into `content`. Pass
    `extra_body={"think": False}` to force plain-content output.

- LM Studio (OpenAI-compatible) + qwen3 family:
    a) `api_key` is not validated but must be non-empty; we send a
       placeholder.
    b) Thinking mode is still on; set
       `extra_body={"chat_template_kwargs": {"enable_thinking": False}}`
       to disable (effect depends on the loaded chat template).
    c) Qwen3's native `<tool_call>...</tool_call>` XML leaks into
       `content` / `reasoning_content` because LM Studio's default tool
       parser does not understand Qwen's training-time format. We
       recover it here; the kernel never sees the leak.

Both forms of the Qwen native block are supported:
    1) JSON form: <tool_call>{"name": "X", "arguments": {...}}</tool_call>
    2) XML  form: <tool_call><function=X><parameter=K>V</parameter>...</function></tool_call>
"""

from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any

from litellm import completion

from traceweaver.core.intelligence.base import (
    Intelligence,
    IntelligenceRequest,
    IntelligenceResponse,
)
from traceweaver.core.types import Message, ToolCall


# ---- Qwen native tool-call normalization ---------------------------------

_TOOL_CALL_BLOCK = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)
_XML_FUNCTION = re.compile(r"<function=([\w.\-]+)>")
_XML_PARAMETER = re.compile(
    r"<parameter=([\w.\-]+)>\s*(.*?)\s*</parameter>", re.DOTALL
)


def _coerce_xml_value(raw: str, expected: str | None) -> Any:
    if expected == "integer":
        try:
            return int(raw)
        except ValueError:
            return raw
    if expected == "number":
        try:
            return float(raw)
        except ValueError:
            return raw
    if expected == "boolean":
        return raw.strip().lower() in ("true", "1", "yes")
    return raw


def extract_leaked_tool_calls(
    text: str | None,
    tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Parse Qwen-native tool-call blocks that some providers leak into
    plain text instead of returning as structured OpenAI `tool_calls`.

    Returns a list of `{"name": str, "arguments": dict}`; empty list
    when the text doesn't contain any `<tool_call>` block.

    `tools` is the same OpenAI-tool-spec list that was sent to the LLM;
    we use it to coerce XML-form parameter values to their declared
    types (Qwen's XML format is all strings on the wire).
    """
    if not text or "<tool_call>" not in text:
        return []

    param_types: dict[str, dict[str, str]] = {}
    for t in tools:
        fn = t.get("function", {}) or {}
        name = fn.get("name")
        props = (fn.get("parameters") or {}).get("properties", {}) or {}
        if name:
            param_types[name] = {
                k: (v.get("type") if isinstance(v, dict) else None) or "string"
                for k, v in props.items()
            }

    out: list[dict[str, Any]] = []
    for block in _TOOL_CALL_BLOCK.findall(text):
        block = block.strip()

        # 1) JSON form
        parsed: Any = None
        try:
            parsed = json.loads(block)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict) and "name" in parsed:
            args_val = parsed.get("arguments", {})
            if isinstance(args_val, str):
                try:
                    args_val = json.loads(args_val)
                except json.JSONDecodeError:
                    pass
            if not isinstance(args_val, dict):
                args_val = {}
            out.append({"name": parsed["name"], "arguments": args_val})
            continue

        # 2) XML form
        fn_match = _XML_FUNCTION.search(block)
        if not fn_match:
            continue
        tool_name = fn_match.group(1)
        args: dict[str, Any] = {}
        for pm in _XML_PARAMETER.finditer(block):
            key, raw = pm.group(1), pm.group(2).strip()
            expected = param_types.get(tool_name, {}).get(key)
            args[key] = _coerce_xml_value(raw, expected)
        out.append({"name": tool_name, "arguments": args})

    return out


# ---- Message conversion ---------------------------------------------------


def _messages_to_openai(system_prompt: str, messages: list[Message]) -> list[dict]:
    out: list[dict] = [{"role": "system", "content": system_prompt}]
    for m in messages:
        if m.role == "assistant" and m.tool_calls:
            out.append(
                {
                    "role": "assistant",
                    "content": m.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                # Prefer the provider's verbatim argument
                                # string so the chat template sees exactly
                                # what the model originally produced.
                                "arguments": (
                                    tc.arguments_raw
                                    if tc.arguments_raw is not None
                                    else json.dumps(
                                        tc.arguments, ensure_ascii=False
                                    )
                                ),
                            },
                        }
                        for tc in m.tool_calls
                    ],
                }
            )
        elif m.role == "tool":
            # Spec-wise `name` is optional here, but several OpenAI-compatible
            # backends (LM Studio's Qwen flavour among them) behave noticeably
            # better when it is present; they use it to render the tool-result
            # turn in the chat template.
            entry = {
                "role": "tool",
                "tool_call_id": m.tool_call_id or "",
                "content": m.content,
            }
            if m.name:
                entry["name"] = m.name
            out.append(entry)
        else:
            out.append({"role": m.role, "content": m.content})
    return out


# ---- Response parsing -----------------------------------------------------


def _parse_json_from_text(text: str | None) -> dict[str, Any] | None:
    if not text:
        return None
    stripped = text.strip()
    start, end = stripped.find("{"), stripped.rfind("}")
    if start < 0 or end <= start:
        return None
    candidate = stripped[start : end + 1]
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _parse_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        if not raw.strip():
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


# ---- Provider quirk matrix ------------------------------------------------


def _provider_kwargs(model: str, api_base: str | None) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if api_base:
        kwargs["api_base"] = api_base

    lower = model.lower()
    if model.startswith("ollama/"):
        if "qwen3" in lower:
            kwargs["extra_body"] = {"think": False}
    elif model.startswith(("openai/", "lm_studio/")):
        kwargs["api_key"] = os.environ.get("OPENAI_API_KEY", "local-no-key")
        if "qwen3" in lower:
            kwargs["extra_body"] = {
                "chat_template_kwargs": {"enable_thinking": False}
            }
    return kwargs


# ---- The adapter itself ---------------------------------------------------


class LLMIntelligence(Intelligence):
    """
    Drive a chat model through litellm and present the kernel with a
    provider-neutral `IntelligenceResponse`.

    Parameters
    ----------
    model:
        litellm-style model id (e.g. `openai/qwen/qwen3.5-9b`,
        `ollama/qwen2.5:7b`).
    api_base:
        Optional endpoint override (e.g. `http://127.0.0.1:1234/v1` for
        LM Studio, `http://127.0.0.1:11434` for Ollama).
    temperature:
        Sampling temperature. Defaults to 0.0 for deterministic
        diagnosis.
    extra_completion_kwargs:
        Escape hatch for callers that need to pass exotic litellm
        params. Merged on top of provider-derived kwargs.
    """

    def __init__(
        self,
        model: str,
        api_base: str | None = None,
        temperature: float = 0.0,
        extra_completion_kwargs: dict[str, Any] | None = None,
    ) -> None:
        self.model = model
        self.api_base = api_base
        self.temperature = temperature
        self.name = f"LLMIntelligence[{model}]"
        self._extra = dict(extra_completion_kwargs or {})

    # ---- main entry point -------------------------------------------------

    def think(self, request: IntelligenceRequest) -> IntelligenceResponse:
        call_kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": _messages_to_openai(request.system_prompt, request.messages),
            "temperature": self.temperature,
        }
        if request.tools:
            call_kwargs["tools"] = request.tools
        call_kwargs.update(_provider_kwargs(self.model, self.api_base))
        call_kwargs.update(self._extra)

        resp = completion(**call_kwargs)
        return self._parse_completion(resp, request)

    # ---- response normalization ------------------------------------------

    def _parse_completion(
        self,
        resp: Any,
        request: IntelligenceRequest,
    ) -> IntelligenceResponse:
        msg = resp.choices[0].message
        content = getattr(msg, "content", None) or ""
        reasoning = (
            getattr(msg, "reasoning_content", None)
            or getattr(msg, "reasoning", None)
            or ""
        )
        native_tool_calls = getattr(msg, "tool_calls", None) or []

        tool_calls = [
            ToolCall(
                id=(getattr(tc, "id", None) or f"call-{uuid.uuid4().hex[:10]}"),
                name=tc.function.name,
                arguments=_parse_arguments(tc.function.arguments),
                arguments_raw=(
                    tc.function.arguments
                    if isinstance(tc.function.arguments, str)
                    else None
                ),
            )
            for tc in native_tool_calls
        ]

        # Qwen native leak recovery: only when the provider gave us no
        # structured tool_calls. Honour precedence: content first, then
        # reasoning_content.
        if not tool_calls:
            for src in (content, reasoning):
                leaked = extract_leaked_tool_calls(src, request.tools)
                if leaked:
                    tool_calls = [
                        ToolCall(
                            id=f"extracted-{uuid.uuid4().hex[:10]}",
                            name=ec["name"],
                            arguments=ec["arguments"],
                        )
                        for ec in leaked
                    ]
                    break

        if tool_calls:
            return IntelligenceResponse(
                kind="tool_calls",
                tool_calls=tool_calls,
                reasoning=reasoning or None,
                assistant_content=content,
            )

        # No tool calls => final answer.
        final_text = content or reasoning or ""
        final_json: dict[str, Any] | None = None
        if request.response_schema is not None:
            final_json = _parse_json_from_text(content) or _parse_json_from_text(
                reasoning
            )

        return IntelligenceResponse(
            kind="final",
            final_text=final_text,
            final_json=final_json,
            reasoning=reasoning or None,
            assistant_content=content,
        )


__all__ = ["LLMIntelligence", "extract_leaked_tool_calls"]
