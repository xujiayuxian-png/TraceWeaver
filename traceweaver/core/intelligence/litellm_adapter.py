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
        elif "minimax" in lower:
            # MiniMax reasoning models embed <think>...</think> in
            # `content` by default. `reasoning_split=True` moves the
            # thinking into `reasoning_details` so `content` contains
            # only the final answer / tool-call payload.
            kwargs["extra_body"] = {"reasoning_split": True}
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
        # MiniMax requires temperature in (0, 1], not [0, 1]
        # Clamp 0.0 to minimum 0.05 to avoid provider rejection
        self.temperature = (
            max(0.05, temperature) if "minimax" in model.lower() else temperature
        )
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
        raw_content = getattr(msg, "content", None) or ""
        reasoning = (
            getattr(msg, "reasoning_content", None)
            or getattr(msg, "reasoning", None)
            or _extract_reasoning_details(msg)
            or ""
        )
        # Some reasoning models (MiniMax M2.x default mode, vLLM Qwen
        # with thinking on, ...) embed <think>...</think> segments in
        # `content`. Move that text into `reasoning` and leave content
        # with just the answer / tool JSON.
        stripped_content, leaked_reasoning = _split_think_tags(raw_content)
        content = stripped_content
        if leaked_reasoning and not reasoning:
            reasoning = leaked_reasoning
        elif leaked_reasoning:
            reasoning = f"{reasoning}\n{leaked_reasoning}" if reasoning else leaked_reasoning
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

        # No tool calls => final answer.
        final_text = content or reasoning or ""
        final_json: dict[str, Any] | None = None
        if request.response_schema is not None:
            final_json = _parse_json_from_text(content) or _parse_json_from_text(
                reasoning
            )

        # Extract telemetry from response (P1.1)
        total_tokens, total_cost_usd = _extract_usage(resp, self.model)

        if tool_calls:
            return IntelligenceResponse(
                kind="tool_calls",
                tool_calls=tool_calls,
                reasoning=reasoning or None,
                assistant_content=content,
                total_tokens=total_tokens,
                total_cost_usd=total_cost_usd,
            )

        return IntelligenceResponse(
            kind="final",
            final_text=final_text,
            final_json=final_json,
            reasoning=reasoning or None,
            assistant_content=content,
            total_tokens=total_tokens,
            total_cost_usd=total_cost_usd,
        )


_THINK_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL | re.IGNORECASE)


def _split_think_tags(text: str) -> tuple[str, str]:
    """
    Return (content_without_think, concatenated_think_bodies).

    If the model emitted `<think>A</think>actual answer`, we want the
    kernel to see `actual answer` as content and `A` as reasoning.
    """
    if not text or "<think" not in text.lower():
        return text, ""
    bodies = _THINK_RE.findall(text)
    cleaned = _THINK_RE.sub("", text).strip()
    # Also drop dangling open <think> with no close (partial stream, length cut-off)
    if "<think>" in cleaned.lower():
        idx = cleaned.lower().find("<think>")
        cleaned = cleaned[:idx].strip()
    return cleaned, "\n".join(b.strip() for b in bodies if b.strip())


def _extract_reasoning_details(msg: Any) -> str:
    """
    MiniMax with `reasoning_split=True` returns:
      message.reasoning_details = [{"text": "..."}, ...]
    """
    details = getattr(msg, "reasoning_details", None)
    if not details:
        return ""
    texts: list[str] = []
    for d in details:
        if isinstance(d, dict):
            t = d.get("text")
        else:
            t = getattr(d, "text", None)
        if t:
            texts.append(str(t))
    return "\n".join(texts)


def _get_usage_field(usage: Any, key: str) -> int:
    """Read a field from usage, tolerating both dict and attribute styles."""
    if usage is None:
        return 0
    if isinstance(usage, dict):
        val = usage.get(key)
    else:
        val = getattr(usage, key, None)
    try:
        return int(val) if val is not None else 0
    except (TypeError, ValueError):
        return 0


def _extract_usage(resp: Any, model: str) -> tuple[int | None, float | None]:
    """
    Extract token usage and estimated cost from litellm response.
    Returns (tokens_used, cost_usd) or (None, None) if not available.

    litellm returns `usage` as either a Pydantic model (OpenAI-style)
    or a plain dict depending on provider; we accept both.
    """
    usage = getattr(resp, "usage", None)
    if usage is None:
        return None, None

    prompt_tokens = _get_usage_field(usage, "prompt_tokens")
    completion_tokens = _get_usage_field(usage, "completion_tokens")
    total_tokens = _get_usage_field(usage, "total_tokens")

    if not total_tokens and (prompt_tokens or completion_tokens):
        total_tokens = prompt_tokens + completion_tokens

    if not total_tokens:
        return None, None

    # Rough cost estimation (per 1M tokens) - local/unknown models = 0
    model_lower = model.lower()
    if "gpt-4" in model_lower and "turbo" not in model_lower:
        # GPT-4: $30/$60 per 1M
        cost = (prompt_tokens * 30 + completion_tokens * 60) / 1_000_000
    elif "gpt-4-turbo" in model_lower or "gpt-4-0125" in model_lower:
        # GPT-4-turbo: $10/$30 per 1M
        cost = (prompt_tokens * 10 + completion_tokens * 30) / 1_000_000
    elif "gpt-3.5" in model_lower or "gpt-35" in model_lower:
        # GPT-3.5-turbo: $0.5/$1.5 per 1M
        cost = (prompt_tokens * 0.5 + completion_tokens * 1.5) / 1_000_000
    elif "claude-3-opus" in model_lower:
        # Claude 3 Opus: $15/$75 per 1M
        cost = (prompt_tokens * 15 + completion_tokens * 75) / 1_000_000
    elif "claude-3-sonnet" in model_lower:
        # Claude 3 Sonnet: $3/$15 per 1M
        cost = (prompt_tokens * 3 + completion_tokens * 15) / 1_000_000
    elif "claude-3-haiku" in model_lower:
        # Claude 3 Haiku: $0.25/$1.25 per 1M
        cost = (prompt_tokens * 0.25 + completion_tokens * 1.25) / 1_000_000
    elif "minimax" in model_lower:
        # MiniMax: rough estimate $1/$2 per 1M
        cost = (prompt_tokens * 1 + completion_tokens * 2) / 1_000_000
    else:
        # Local models (LM Studio, Ollama) or unknown: cost = 0
        cost = 0.0

    return total_tokens, cost


__all__ = ["LLMIntelligence", "extract_leaked_tool_calls"]
