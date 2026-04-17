#!/usr/bin/env python3
"""
Tool Calling 能力验证脚本 (TraceWeaver v2 M1 前置门槛)

目标
----
在投入 v2 重构前，确认基线模型 (默认 ollama/qwen3.5:9b) 能**稳定**完成
OpenAI 风格的 function calling（tool calling）。如果模型不能稳定调用
工具、按 schema 返回参数、遵循轮次边界，v2 的 Agent Kernel 就不能基于
tool calling 循环来实现，整个架构需要重新评估。

本脚本不依赖 TraceWeaver 代码，单文件可跑。

前置要求
--------
- Python 3.11+
- `pip install litellm>=1.40 pydantic>=2.8`
- Ollama 已运行，模型已 pull 好：
    ollama serve
    ollama pull qwen2.5:9b    # 或 qwen3:9b / qwen3.5:9b（视可用性）
- 环境变量 (可选):
    OLLAMA_API_BASE   默认 http://127.0.0.1:11434
    TW_VALIDATE_MODEL 默认 ollama/qwen3.5:9b
    TW_VALIDATE_ROUNDS 默认 5 (每个任务最大轮数)

跑法
----
    python scripts/validate_tool_calling.py
    python scripts/validate_tool_calling.py --model ollama/qwen2.5:14b
    python scripts/validate_tool_calling.py --model openai/gpt-4o-mini

退出码
------
    0: 通过 (成功率 >= 通过阈值)
    1: 失败 (模型不满足 v2 基线需求)
    2: 环境问题 (litellm 未装 / 连不上 ollama / ...)

输出
----
- 控制台：每个任务的结果 + 最终总结
- 文件：.traceweaver/validate_tool_calling_<timestamp>.json
  含完整调用轨迹，便于复盘

说明
----
脚本内置 5 个渐进难度的任务，覆盖 v2 Agent Kernel 会用到的所有能力：
  T1: 单工具调用 + 参数正确
  T2: 按 schema 返回最终结构化输出
  T3: 多轮 tool call (2 轮)
  T4: 拒绝调用无意义工具 (控制 parallel/avoidance)
  T5: 复合任务 (tool call + schema output 组合)

只要 5 个任务全部通过 2/3 以上尝试，就算通过基线。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from litellm import completion
except ImportError:
    print(
        "ERROR: litellm 未安装。请运行：pip install 'litellm>=1.40'",
        file=sys.stderr,
    )
    sys.exit(2)


# ============================================================
# 配置
# ============================================================

DEFAULT_MODEL = os.environ.get("TW_VALIDATE_MODEL", "ollama/qwen3.5:9b")
DEFAULT_API_BASE = os.environ.get("OLLAMA_API_BASE", "http://127.0.0.1:11434")
DEFAULT_MAX_ROUNDS = int(os.environ.get("TW_VALIDATE_ROUNDS", "5"))

# 每个 provider 默认连的 base URL；用户显式传 --api-base 会覆盖
PROVIDER_DEFAULT_API_BASE = {
    "ollama": "http://127.0.0.1:11434",
    "lm_studio": "http://127.0.0.1:1234/v1",
    # openai/* 前缀如果配合本地兼容服务，需要用户显式 --api-base 覆盖
}

# 每个任务跑几次取多数
ATTEMPTS_PER_TASK = 3
PASS_THRESHOLD = 2  # 3 次里通过 >=2 次算该任务通过

# 所有任务都通过才算基线达标
MIN_TASKS_PASSED = 5  # 总共 5 个任务


# ============================================================
# 模拟工具
# ============================================================

TOOLS_SPEC = [
    {
        "type": "function",
        "function": {
            "name": "get_session_count",
            "description": "Return how many UE sessions exist in the capture.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_session_info",
            "description": "Get details of a specific session by index.",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_index": {
                        "type": "integer",
                        "description": "0-based index of the session",
                        "minimum": 0,
                    }
                },
                "required": ["session_index"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_frame_at",
            "description": "Get the raw frame record at a specific frame number.",
            "parameters": {
                "type": "object",
                "properties": {
                    "frame_number": {
                        "type": "integer",
                        "description": "1-based frame number as in tshark output",
                        "minimum": 1,
                    }
                },
                "required": ["frame_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": "Search the 3GPP knowledge base for cause codes or procedures.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Free-text query",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "echo",
            "description": (
                "A debug-only tool that echoes the input. DO NOT call this unless "
                "the user explicitly asks you to test echoing. It has no diagnostic value."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                },
                "required": ["text"],
            },
        },
    },
]

MOCK_DATA = {
    "session_count": 2,
    "sessions": [
        {
            "index": 0,
            "session_id": "ue-session-1",
            "ran_ue_ngap_id": 100,
            "amf_ue_ngap_id": 200,
            "events": ["REGISTRATION_REQUEST", "AUTHENTICATION_FAILURE"],
        },
        {
            "index": 1,
            "session_id": "ue-session-2",
            "ran_ue_ngap_id": 101,
            "amf_ue_ngap_id": 201,
            "events": ["REGISTRATION_REQUEST", "REGISTRATION_ACCEPT"],
        },
    ],
    "frames": {
        42: {
            "frame_number": 42,
            "protocol": "nas_5gs",
            "event": "AUTHENTICATION_FAILURE",
            "cause": 20,  # MAC failure
        },
    },
    "knowledge": {
        "cause 20": (
            "5GMM cause 20 (MAC failure): the MAC in the AUTHENTICATION RESPONSE "
            "was incorrect. Typical root cause: SIM-side key (K) mismatch with UDM subscription."
        ),
    },
}


def _extract_tool_calls_from_text(text: str) -> list[dict]:
    """
    v2 Layer 4 适配器归一化：
    某些 provider（典型：LM Studio 非 Native 列表里的模型，如 Qwen3 系列）
    不会把模型训练原生的 <tool_call>...</tool_call> 文本翻译为 OpenAI
    结构化 tool_calls 字段，而是放进 content / reasoning_content。
    本函数把这类泄漏的 tool call 提取为规范化字典列表。

    支持两种内部格式（都包在 <tool_call>...</tool_call> 里）：
      1. JSON 形式：{"name": "X", "arguments": {...}}
      2. XML 形式 ：<function=X><parameter=K>V</parameter>...</function>

    返回 [{"name": str, "arguments": dict}, ...]
    """
    import re

    if not text or "<tool_call>" not in text:
        return []

    param_types: dict[str, dict[str, str]] = {}
    for t in TOOLS_SPEC:
        fn = t.get("function", {})
        tn = fn.get("name")
        props = fn.get("parameters", {}).get("properties", {})
        if tn:
            param_types[tn] = {k: v.get("type", "string") for k, v in props.items()}

    results: list[dict] = []
    for block in re.findall(r"<tool_call>\s*(.*?)\s*</tool_call>", text, re.DOTALL):
        block = block.strip()

        # 1) JSON form
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
            results.append({"name": parsed["name"], "arguments": args_val})
            continue

        # 2) XML form
        fn_match = re.search(r"<function=([\w.\-]+)>", block)
        if not fn_match:
            continue
        tool_name = fn_match.group(1)
        args: dict[str, Any] = {}
        for pm in re.finditer(
            r"<parameter=([\w.\-]+)>\s*(.*?)\s*</parameter>", block, re.DOTALL
        ):
            key, raw = pm.group(1), pm.group(2).strip()
            expected = param_types.get(tool_name, {}).get(key, "string")
            coerced: Any = raw
            if expected == "integer":
                try:
                    coerced = int(raw)
                except ValueError:
                    pass
            elif expected == "number":
                try:
                    coerced = float(raw)
                except ValueError:
                    pass
            elif expected == "boolean":
                coerced = raw.lower() in ("true", "1", "yes")
            args[key] = coerced
        results.append({"name": tool_name, "arguments": args})

    return results


def execute_tool(name: str, args: dict) -> dict:
    """模拟工具执行。"""
    if name == "get_session_count":
        return {"count": MOCK_DATA["session_count"]}
    if name == "get_session_info":
        idx = args.get("session_index")
        if not isinstance(idx, int) or idx < 0 or idx >= MOCK_DATA["session_count"]:
            return {"error": f"invalid session_index: {idx}"}
        return MOCK_DATA["sessions"][idx]
    if name == "get_frame_at":
        frame = args.get("frame_number")
        if frame in MOCK_DATA["frames"]:
            return MOCK_DATA["frames"][frame]
        return {"error": f"frame {frame} not found"}
    if name == "search_knowledge":
        q = (args.get("query") or "").lower()
        for key, val in MOCK_DATA["knowledge"].items():
            key_tokens = [t for t in key.lower().split() if t]
            if key_tokens and all(t in q for t in key_tokens):
                return {"result": val}
        return {"result": "no matching entry"}
    if name == "echo":
        return {"echoed": args.get("text", "")}
    return {"error": f"unknown tool: {name}"}


# ============================================================
# 验证任务定义
# ============================================================


@dataclass
class Task:
    name: str
    description: str
    system_prompt: str
    user_prompt: str
    # 判定标准：给完整对话轨迹和最终输出，返回 (passed, reason)
    check: Any  # callable(trace, final_content) -> (bool, str)
    # 是否要求返回 JSON 结构化输出
    require_json: bool = False
    response_schema: dict | None = None


def _has_tool_call(trace: list[dict], tool_name: str) -> bool:
    for entry in trace:
        for call in entry.get("tool_calls", []):
            if call["name"] == tool_name:
                return True
    return False


def _count_tool_calls(trace: list[dict]) -> int:
    return sum(len(entry.get("tool_calls", [])) for entry in trace)


def _called_tool_with_valid_args(
    trace: list[dict], tool_name: str, validate_args
) -> bool:
    for entry in trace:
        for call in entry.get("tool_calls", []):
            if call["name"] == tool_name:
                try:
                    if validate_args(call["args"]):
                        return True
                except Exception:
                    continue
    return False


def check_t1(trace, final_content):
    total = _count_tool_calls(trace)
    if total == 0:
        return False, "expected to call get_session_count"
    if _has_tool_call(trace, "echo"):
        return False, "should not call echo tool"
    if not _has_tool_call(trace, "get_session_count"):
        return False, "the call should be get_session_count"
    if total > 1:
        names = [c["name"] for e in trace for c in e.get("tool_calls", [])]
        return False, f"expected exactly 1 tool call (just get_session_count), got {total}: {names}"
    text = final_content if isinstance(final_content, str) else json.dumps(final_content, ensure_ascii=False)
    if "2" not in text:
        return False, f"final answer should mention the count (2), got: {text[:200]}"
    return True, "ok"


def check_t2(trace, final_content):
    if _has_tool_call(trace, "echo"):
        return False, "should NOT call echo tool to emit the final JSON"
    if not isinstance(final_content, dict):
        return False, f"final output is not a dict: {type(final_content).__name__}"
    verdict = final_content.get("verdict")
    if verdict not in ["OK", "FAIL", "INCONCLUSIVE"]:
        return False, f"verdict not in enum: {verdict}"
    if verdict != "FAIL":
        return False, f"expected verdict=FAIL (session 0 has AUTHENTICATION_FAILURE), got {verdict}"
    if "reason" not in final_content:
        return False, "missing reason field"
    return True, "ok"


def check_t3(trace, final_content):
    if not _has_tool_call(trace, "get_session_count"):
        return False, "expected to call get_session_count first"
    if not _called_tool_with_valid_args(
        trace, "get_session_info", lambda args: args.get("session_index") == 1
    ):
        return False, "expected to call get_session_info with session_index=1 (the last session)"
    return True, "ok"


def check_t4(trace, final_content):
    if _has_tool_call(trace, "echo"):
        return False, "should NOT call echo tool (it's marked as debug-only)"
    useful_tools = {"get_session_count", "get_session_info", "get_frame_at", "search_knowledge"}
    any_useful = any(
        call["name"] in useful_tools
        for entry in trace
        for call in entry.get("tool_calls", [])
    )
    if not any_useful:
        return False, "expected to call at least one diagnostic tool"
    return True, "ok"


def check_t5(trace, final_content):
    if not _has_tool_call(trace, "get_frame_at"):
        return False, "expected to call get_frame_at"
    if not _has_tool_call(trace, "search_knowledge"):
        return False, "expected to call search_knowledge"
    if not isinstance(final_content, dict):
        return False, "final output is not a dict"
    if final_content.get("verdict") != "FAIL":
        return False, f"expected verdict=FAIL, got {final_content.get('verdict')}"
    if final_content.get("cause_code") != 20:
        return False, f"expected cause_code=20, got {final_content.get('cause_code')}"
    explanation = (final_content.get("explanation") or "").lower()
    # search_knowledge 明确返回 "MAC failure"; explanation 若没提 MAC 就是没 ground 在工具返回上
    if "mac" not in explanation:
        return False, (
            "explanation not grounded in search_knowledge result "
            f"(missing 'MAC'): {explanation[:180]}"
        )
    return True, "ok"


TASKS = [
    Task(
        name="T1_single_tool_call",
        description="Single tool call with no arguments",
        system_prompt=(
            "You are a pcap analysis assistant. Use tools to answer questions. "
            "Only call tools that help answer the user's question. "
            "When done, give a short final answer."
        ),
        user_prompt="How many UE sessions are in this capture?",
        check=check_t1,
    ),
    Task(
        name="T2_structured_output",
        description="Return structured JSON per schema",
        system_prompt=(
            "You are a pcap analyzer. Use tools to investigate, then output the final "
            "structured verdict as a plain JSON object in your assistant message content. "
            "Do NOT call any tool to emit the final JSON — write it directly as your answer."
        ),
        user_prompt=(
            "Check session at index 0 and tell me if registration succeeded or failed. "
            "Output JSON with fields: verdict (OK/FAIL/INCONCLUSIVE), reason (string)."
        ),
        check=check_t2,
        require_json=True,
        response_schema={
            "type": "object",
            "properties": {
                "verdict": {"type": "string", "enum": ["OK", "FAIL", "INCONCLUSIVE"]},
                "reason": {"type": "string"},
            },
            "required": ["verdict", "reason"],
        },
    ),
    Task(
        name="T3_multi_round",
        description="Multi-round tool calling with dependency",
        system_prompt=(
            "You are a pcap analyzer. To answer, first check how many sessions exist, "
            "then examine the last one. Call tools one at a time."
        ),
        user_prompt="Examine the last UE session in the capture and summarize what happened.",
        check=check_t3,
    ),
    Task(
        name="T4_avoid_irrelevant_tool",
        description="Must NOT call tools marked irrelevant",
        system_prompt=(
            "You are a pcap analyzer. Use relevant tools only. "
            "Read tool descriptions carefully before calling."
        ),
        user_prompt="Diagnose session at index 0 and tell me what went wrong.",
        check=check_t4,
    ),
    Task(
        name="T5_compound",
        description="Compound: frame lookup + knowledge lookup + structured output",
        system_prompt=(
            "You are a 5G Core diagnosis expert. Use tools to investigate, then output "
            "the final structured verdict as a plain JSON object in your assistant message "
            "content. Do NOT call any tool to emit the final JSON — write it directly as "
            "your answer."
        ),
        user_prompt=(
            "Frame 42 contains an authentication failure. Look up the frame, look up "
            "what its cause code means, then output JSON with fields: "
            "verdict (OK/FAIL/INCONCLUSIVE), cause_code (int), explanation (string)."
        ),
        check=check_t5,
        require_json=True,
        response_schema={
            "type": "object",
            "properties": {
                "verdict": {"type": "string", "enum": ["OK", "FAIL", "INCONCLUSIVE"]},
                "cause_code": {"type": "integer"},
                "explanation": {"type": "string"},
            },
            "required": ["verdict", "cause_code", "explanation"],
        },
    ),
]


# ============================================================
# Tool calling loop
# ============================================================


@dataclass
class AttemptResult:
    task_name: str
    attempt_index: int
    passed: bool
    reason: str
    trace: list[dict] = field(default_factory=list)
    final_content: Any = None
    rounds_used: int = 0
    error: str | None = None
    elapsed_s: float = 0.0


def run_tool_calling_loop(
    task: Task,
    model: str,
    api_base: str | None,
    max_rounds: int,
) -> AttemptResult:
    started = time.perf_counter()

    messages: list[dict] = [
        {"role": "system", "content": task.system_prompt},
        {"role": "user", "content": task.user_prompt},
    ]

    trace: list[dict] = []
    final_content: Any = None

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "tools": TOOLS_SPEC,
        "temperature": 0.0,
    }
    if api_base:
        kwargs["api_base"] = api_base
    if model.startswith("ollama/"):
        # qwen3 系列默认会开 thinking，OpenAI 兼容接口会返回空 content，v1 验证过要关掉
        kwargs["extra_body"] = {"think": False}
    elif model.startswith(("openai/", "lm_studio/")):
        # litellm openai provider 要求一个 key；本地兼容服务不校验内容
        kwargs["api_key"] = os.environ.get("OPENAI_API_KEY", "local-no-key")
        if "qwen3" in model.lower():
            # Qwen3 家族默认走 thinking 模式；关掉让它直接输出（chat template 需支持）
            kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}

    for round_idx in range(1, max_rounds + 1):
        try:
            resp = completion(**kwargs)
        except Exception as exc:
            return AttemptResult(
                task_name=task.name,
                attempt_index=0,
                passed=False,
                reason=f"LLM call failed: {exc}",
                trace=trace,
                rounds_used=round_idx,
                error=str(exc),
                elapsed_s=time.perf_counter() - started,
            )

        msg = resp.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None) or []
        reasoning_text = (
            getattr(msg, "reasoning_content", None)
            or getattr(msg, "reasoning", None)
            or ""
        )
        msg_content = getattr(msg, "content", "") or ""

        entry: dict[str, Any] = {
            "round": round_idx,
            "assistant_content": msg_content,
            "reasoning_content": reasoning_text,
            "tool_calls": [],
        }

        # v2 Layer 4 归一化兜底：API 没给 tool_calls 但原文里漏出 <tool_call> XML
        extracted: list[dict] = []
        if not tool_calls:
            for src in (msg_content, reasoning_text):
                extracted = _extract_tool_calls_from_text(src)
                if extracted:
                    break
        if extracted:
            import uuid
            from types import SimpleNamespace

            tool_calls = [
                SimpleNamespace(
                    id=f"extracted-{uuid.uuid4().hex[:10]}",
                    type="function",
                    function=SimpleNamespace(
                        name=ec["name"],
                        arguments=json.dumps(ec["arguments"], ensure_ascii=False),
                    ),
                )
                for ec in extracted
            ]
            entry["_extracted_from_text"] = True

        if tool_calls:
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError as exc:
                    args = {}
                    entry["tool_calls"].append(
                        {
                            "name": name,
                            "args": {},
                            "result": {"error": f"invalid JSON arguments: {exc}"},
                            "arg_parse_error": True,
                        }
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps({"error": "invalid JSON in arguments"}),
                        }
                    )
                    continue

                result = execute_tool(name, args)
                entry["tool_calls"].append(
                    {"name": name, "args": args, "result": result}
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result),
                    }
                )

            trace.append(entry)
            kwargs["messages"] = messages
            continue

        # 没有 tool_calls → 最终输出
        content_text = (msg.content or "").strip()
        entry["final"] = True
        entry["final_content_raw"] = content_text
        trace.append(entry)

        # 某些 provider（LM Studio 上的 Qwen3 / 任何带 reasoning 的模型）会把最终答案的文本
        # 放在 content 里，但把 JSON 之类结构化输出夹在 reasoning_content 里。
        # Kernel 兜底：content 没有可用值就回落到 reasoning_content。
        def _effective_text() -> str:
            if content_text:
                return content_text
            return reasoning_text.strip()

        if task.require_json:
            parsed = _parse_json_from_text(content_text)
            if parsed is None and reasoning_text:
                parsed = _parse_json_from_text(reasoning_text)
            final_content = parsed
        else:
            final_content = _effective_text()
        break
    else:
        return AttemptResult(
            task_name=task.name,
            attempt_index=0,
            passed=False,
            reason=f"exceeded max_rounds={max_rounds} without final answer",
            trace=trace,
            rounds_used=max_rounds,
            elapsed_s=time.perf_counter() - started,
        )

    passed, reason = task.check(trace, final_content)
    return AttemptResult(
        task_name=task.name,
        attempt_index=0,
        passed=passed,
        reason=reason,
        trace=trace,
        final_content=final_content,
        rounds_used=round_idx,
        elapsed_s=time.perf_counter() - started,
    )


def _parse_json_from_text(text: str) -> Any:
    """尽力从文本里提取 JSON (裸 JSON / 带 ```json 包裹 / 夹在散文里)。"""
    text = text.strip()
    # Case 1: 裸 JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Case 2: ```json ... ``` 代码块
    import re

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            pass
    # Case 3: 第一个 { 到配对的 }
    brace_start = text.find("{")
    if brace_start != -1:
        depth = 0
        for i in range(brace_start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[brace_start : i + 1])
                    except json.JSONDecodeError:
                        break
    return None


# ============================================================
# 主流程
# ============================================================


def main() -> int:
    # Windows PowerShell 默认 GBK，打印 unicode 符号会崩；强制 stdout UTF-8
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"default: {DEFAULT_MODEL}")
    parser.add_argument(
        "--api-base",
        default=None,
        help="Override API base URL (auto-picked by provider prefix if omitted)",
    )
    parser.add_argument("--max-rounds", type=int, default=DEFAULT_MAX_ROUNDS)
    parser.add_argument("--attempts", type=int, default=ATTEMPTS_PER_TASK)
    parser.add_argument("--output-dir", default=".traceweaver", help="Where to write report JSON")
    args = parser.parse_args()

    provider = args.model.split("/", 1)[0] if "/" in args.model else ""
    api_base = args.api_base or PROVIDER_DEFAULT_API_BASE.get(provider)

    print(f"{'=' * 72}")
    print(f"TraceWeaver v2 Tool Calling 基线验证")
    print(f"{'=' * 72}")
    print(f"Model:      {args.model}")
    print(f"API base:   {api_base or '(provider default)'}")
    print(f"Max rounds: {args.max_rounds}")
    print(f"Attempts:   {args.attempts} per task")
    print(f"Pass gate:  {PASS_THRESHOLD}/{args.attempts} attempts per task; all {MIN_TASKS_PASSED} tasks must pass")
    print(f"{'=' * 72}\n")

    all_results: list[AttemptResult] = []
    task_pass_status: dict[str, bool] = {}

    for task in TASKS:
        print(f"[{task.name}] {task.description}")
        task_attempts: list[AttemptResult] = []
        for attempt_i in range(1, args.attempts + 1):
            print(f"  Attempt {attempt_i}/{args.attempts}...", end=" ", flush=True)
            result = run_tool_calling_loop(task, args.model, api_base, args.max_rounds)
            result.attempt_index = attempt_i
            task_attempts.append(result)
            all_results.append(result)
            status = "PASS" if result.passed else "FAIL"
            print(f"{status} ({result.rounds_used} rounds, {result.elapsed_s:.1f}s) — {result.reason}")
        passes = sum(1 for r in task_attempts if r.passed)
        task_passed = passes >= PASS_THRESHOLD
        task_pass_status[task.name] = task_passed
        verdict = "PASS" if task_passed else "FAIL"
        print(f"  → Task {task.name}: {verdict} ({passes}/{args.attempts})\n")

    tasks_passed_count = sum(1 for v in task_pass_status.values() if v)
    overall_passed = tasks_passed_count >= MIN_TASKS_PASSED

    print(f"{'=' * 72}")
    print(f"总结")
    print(f"{'=' * 72}")
    print(f"  通过任务: {tasks_passed_count}/{len(TASKS)}")
    for tname, tpass in task_pass_status.items():
        print(f"    {'✔' if tpass else '✘'} {tname}")
    print()
    if overall_passed:
        print(f"  基线验证通过 — qwen3.5:9b（或所选模型）可用于 v2 Agent Kernel")
    else:
        print(f"  基线验证未通过")
        print(f"  建议：")
        print(f"    1. 尝试 Qwen2.5-14B-Instruct 或 Llama-3.1-70B-Instruct")
        print(f"    2. 检查 ollama 版本是否最新 (ollama --version)")
        print(f"    3. 查看报告 json 找出哪类任务最难（常见：参数格式 / JSON schema）")
    print(f"{'=' * 72}\n")

    # 写报告
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    report_path = output_dir / f"validate_tool_calling_{timestamp}.json"
    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "model": args.model,
        "api_base": api_base,
        "max_rounds": args.max_rounds,
        "attempts_per_task": args.attempts,
        "pass_threshold": PASS_THRESHOLD,
        "overall_passed": overall_passed,
        "tasks_passed": tasks_passed_count,
        "tasks_total": len(TASKS),
        "task_status": task_pass_status,
        "attempts": [
            {
                "task": r.task_name,
                "attempt": r.attempt_index,
                "passed": r.passed,
                "reason": r.reason,
                "rounds_used": r.rounds_used,
                "elapsed_s": round(r.elapsed_s, 2),
                "error": r.error,
                "final_content": r.final_content,
                "trace": r.trace,
            }
            for r in all_results
        ],
    }
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"详细报告已写入: {report_path}\n")

    return 0 if overall_passed else 1


if __name__ == "__main__":
    sys.exit(main())
