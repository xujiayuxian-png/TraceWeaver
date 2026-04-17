from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

import litellm

logger = logging.getLogger(__name__)

MODEL_TIER_MAP: dict[str, str] = {
    "gpt-4": "large",
    "gpt-4o": "large",
    "gpt-4o-mini": "medium",
    "gpt-4.1": "large",
    "gpt-4.1-mini": "medium",
    "gpt-4.1-nano": "small",
    "claude-3-opus": "large",
    "claude-3.5-sonnet": "large",
    "claude-3.5-haiku": "medium",
    "claude-sonnet-4": "large",
    "o3-mini": "large",
    "qwen2.5:72b": "large",
    "qwen2.5:32b": "medium",
    "qwen2.5:14b": "medium",
    "qwen2.5:7b": "small",
    "qwen3:32b": "medium",
    "qwen3:14b": "medium",
    "qwen3:8b": "small",
    "llama3.1:70b": "large",
    "llama3.1:8b": "small",
    "deepseek-r1:32b": "medium",
    "deepseek-r1:14b": "medium",
    "deepseek-r1:8b": "small",
}


def infer_model_tier(model: str) -> str:
    if model in MODEL_TIER_MAP:
        return MODEL_TIER_MAP[model]
    lower = model.lower()
    for key, tier in MODEL_TIER_MAP.items():
        if key in lower:
            return tier
    if any(tag in lower for tag in ("70b", "72b", "gpt-4", "claude-3.5-sonnet", "opus")):
        return "large"
    if any(tag in lower for tag in ("32b", "14b", "medium")):
        return "medium"
    return "small"


@dataclass
class LLMConfig:
    model: str = "ollama/qwen2.5:14b"
    api_base: str | None = None
    api_key: str | None = None
    temperature: float = 0.1
    max_tokens: int = 4096
    timeout: float = 120.0
    max_retries: int = 2
    tier: str | None = None
    extra_params: dict = field(default_factory=dict)

    @property
    def model_tier(self) -> str:
        if self.tier:
            return self.tier
        return infer_model_tier(self.model)


class LLMProvider:
    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        litellm.drop_params = True

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        extra_params = dict(self.config.extra_params)
        extra_body = extra_params.get("extra_body")
        if _should_disable_thinking(self.config.model):
            if extra_body is None:
                extra_params["extra_body"] = {"think": False}
            elif isinstance(extra_body, dict) and "think" not in extra_body:
                extra_params["extra_body"] = {**extra_body, "think": False}

        kwargs: dict = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "timeout": self.config.timeout,
            **extra_params,
        }
        if self.config.api_base:
            kwargs["api_base"] = self.config.api_base
        if self.config.api_key:
            kwargs["api_key"] = self.config.api_key

        logger.debug("LLM request: model=%s tier=%s", self.config.model, self.config.model_tier)

        response = litellm.completion(**kwargs)
        content = response.choices[0].message.content or ""

        logger.debug(
            "LLM response: %d chars, usage=%s",
            len(content),
            getattr(response, "usage", None),
        )
        return content

    def complete_json(self, system_prompt: str, user_prompt: str) -> dict:
        """Call LLM with JSON output enforcement and parse the result."""
        raw = self.complete(system_prompt, user_prompt)
        return _extract_json(raw)


def _should_disable_thinking(model: str) -> bool:
    lower = model.lower()
    return lower.startswith("ollama/qwen3")


def _extract_json(text: str) -> dict:
    stripped = text.strip()

    if stripped.startswith("```"):
        lines = stripped.split("\n")
        start = 1
        if lines[0].strip().startswith("```"):
            start = 1
        end = len(lines)
        for i in range(len(lines) - 1, 0, -1):
            if lines[i].strip() == "```":
                end = i
                break
        stripped = "\n".join(lines[start:end]).strip()

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    brace_start = stripped.find("{")
    brace_end = stripped.rfind("}")
    if brace_start != -1 and brace_end > brace_start:
        try:
            return json.loads(stripped[brace_start : brace_end + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not extract JSON from LLM response:\n{text[:500]}")
