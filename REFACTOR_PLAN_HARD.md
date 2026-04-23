# TraceWeaver 硬核重构计划

> 不兼容。不过渡。直接替换。

---

## 核心原则

1. **core/ 纯协议** — 无 subprocess、pathlib、importlib
2. **builtin/ 全实现** — pcap、file knowledge、builtin tools
3. **无自动注册** — CLI 显式调用 register_builtin_*()
4. **ToolSpec 从 Pydantic 生成** — 删除手动 JSON Schema
5. **删除 likely_*** — summarize_capture 只暴露原始信号

---

## 最终目录

```
traceweaver/
├── core/
│   ├── protocols.py          # 全部抽象基类
│   ├── kernel.py             # AgentKernel (<250行)
│   ├── loop_engine.py        # LoopEngine + LoopState
│   ├── schema_guard.py       # SchemaGuard
│   ├── tool_dispatcher.py    # ToolDispatcher
│   └── trace.py              # AgentTrace, AgentResult
├── builtin/
│   ├── __init__.py           # register_builtin_sources(), register_builtin_tools()
│   ├── sources/              # pcap.py, fake.py, enriched.py
│   ├── tools/                # query_records.py, get_records_around.py, search_knowledge.py
│   └── knowledge/            # file_store.py
├── profiles/open5gs_5gc/     # 6个工具全部用 Pydantic args model
└── recording/                # RecordReplayIntelligence
```

---

## 阶段 A: core/ 纯化

### 1. core/protocols.py (新建)

```python
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Iterator
from pydantic import BaseModel, Field

class Record(BaseModel):
    source: str
    timestamp: float
    seq: int
    key: str = ""
    fields: dict[str, Any] = Field(default_factory=dict)
    raw: str = ""

class SourceSpec(BaseModel):
    kind: str
    uri: str
    options: dict[str, Any] = Field(default_factory=dict)

class SourceHandle(ABC):
    kind: str
    uri: str
    @abstractmethod
    def metadata(self) -> dict[str, Any]: ...
    @abstractmethod
    def iter_records(self, *, filter=None, fields=None, limit=None) -> Iterator[Record]: ...
    @abstractmethod
    def get_records_around(self, seq: int, *, before=2, after=2) -> list[Record]: ...

class Source(ABC):
    kind: str
    @abstractmethod
    def ingest(self, spec: SourceSpec) -> SourceHandle: ...

class ToolSpec(BaseModel):
    name: str
    description: str
    parameters_schema: dict[str, Any] = Field(default_factory=dict)
    
    def to_openai_tool(self) -> dict:
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": self.parameters_schema}}
    
    @classmethod
    def from_pydantic(cls, model: type[BaseModel], name: str, description: str):
        schema = model.model_json_schema()
        schema.pop("$defs", None)
        schema["type"] = "object"
        return cls(name=name, description=description, parameters_schema=schema)

class ToolContext(BaseModel):
    extras: dict[str, Any] = Field(default_factory=dict)
    source_handle: Any | None = None
    scope: Any | None = None
    profile_name: str | None = None
    knowledge_store: Any | None = None

class ToolResult(BaseModel):
    data: dict[str, Any] = Field(default_factory=dict)
    refs: list[str] = Field(default_factory=list)
    truncated: bool = False

class Tool(ABC):
    spec: ToolSpec
    @abstractmethod
    def run(self, ctx: ToolContext, **kwargs) -> ToolResult: ...

class Message(BaseModel):
    role: str
    content: str | None = None
    tool_calls: list[Any] | None = None
    tool_call_id: str | None = None
    name: str | None = None

class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)

class IntelligenceRequest(BaseModel):
    system_prompt: str
    messages: list[Message]
    tools: list[dict] | None = None
    response_schema: dict[str, Any] | None = None

class IntelligenceResponse(BaseModel):
    kind: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    final_text: str | None = None
    final_json: dict | None = None
    reasoning: str | None = None

class Intelligence(ABC):
    @abstractmethod
    def think(self, request: IntelligenceRequest) -> IntelligenceResponse: ...

class KnowledgeHit(BaseModel):
    content: str
    score: float = 0.0

class KnowledgeStore(ABC):
    @abstractmethod
    def search(self, query: str, *, top_k=5, tags=None) -> list[KnowledgeHit]: ...
```

### 2. core/kernel.py

```python
from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Any
from traceweaver.core.protocols import *
from traceweaver.core.loop_engine import LoopEngine
from traceweaver.core.schema_guard import SchemaGuard
from traceweaver.core.tool_dispatcher import ToolDispatcher
from traceweaver.core.trace import AgentResult, AgentTrace, TraceEvent, ToolExecution

@dataclass(frozen=True)
class TaskSpec:
    system_prompt: str
    max_rounds: int = 5
    response_schema: dict | None = None
    forbid_tools: tuple[str, ...] = ()

class AgentKernel:
    def __init__(self, intelligence: Intelligence, tools: list[Tool]):
        self.intelligence = intelligence
        self.dispatcher = ToolDispatcher(tools)
        self.loop_engine = LoopEngine()
        self.schema_guard = SchemaGuard()

    def run(self, task: TaskSpec, user_request: str, ctx: ToolContext | None = None) -> AgentResult:
        ctx = ctx or ToolContext()
        state = self.loop_engine.create_state(task, user_request)
        tools_spec = [t.spec.to_openai_tool() for t in self.dispatcher.tools]

        for round_idx in range(1, task.max_rounds + 1):
            tools_for_round = tools_spec if round_idx < task.max_rounds - 1 else []
            if round_idx >= task.max_rounds - 1:
                state.append_message(Message(role="user", content="Budget exhausted. Return final JSON."))

            try:
                resp = self.intelligence.think(IntelligenceRequest(
                    system_prompt=task.system_prompt,
                    messages=list(state.messages),
                    tools=tools_for_round or None,
                    response_schema=task.response_schema,
                ))
            except Exception as exc:
                return self._finalize(state, "intelligence_error", error=str(exc))

            if resp.kind == "final":
                result = self._handle_final(round_idx, resp, task, state)
                if result:
                    return result
                continue
            self._handle_tool_calls(round_idx, resp, state, ctx, task)

        return self._finalize(state, "max_rounds")

    def _handle_final(self, round_idx, resp, task, state):
        valid, err = self.schema_guard.check(resp.final_json, task.response_schema)
        if valid:
            return self._finalize(state, "final", resp=resp)
        state.append_event(TraceEvent(round_index=round_idx, assistant_content=resp.final_text or "", is_final=False))
        state.append_message(Message(role="assistant", content=resp.final_text or ""))
        state.append_message(Message(role="user", content=f"Schema error: {err}. Retry."))
        state.schema_retries += 1
        if state.schema_retries >= 2:
            return self._finalize(state, "schema_retry_exhausted", resp=resp)
        return None

    def _handle_tool_calls(self, round_idx, resp, state, ctx, task):
        state.append_message(Message(role="assistant", content=resp.assistant_content or "", tool_calls=resp.tool_calls))
        executions = self.dispatcher.dispatch(resp.tool_calls, ctx, task.forbid_tools, state.seen_calls)
        for ex in executions:
            import json
            content = json.dumps({"error": ex.error}, ensure_ascii=False) if not ex.ok else json.dumps({**ex.data, **({"refs": ex.refs} if ex.refs else {}), **({"truncated": True} if ex.truncated else {})}, ensure_ascii=False)
            state.append_message(Message(role="tool", tool_call_id=ex.call.id, name=ex.call.name, content=content))
        state.append_event(TraceEvent(round_index=round_idx, tool_executions=executions, is_final=False, reasoning=resp.reasoning))

    def _finalize(self, state, stop_reason, resp=None, error=None):
        wall_clock = time.perf_counter() - state.t0
        trace = AgentTrace(events=state.events, wall_clock_s=wall_clock)
        return AgentResult(stop_reason=stop_reason, final_text=resp.final_text if resp else None, final_json=resp.final_json if resp else None, trace=trace, error=error, total_tokens=trace.total_tokens(), total_cost_usd=trace.total_cost_usd(), wall_clock_s=wall_clock)
```

### 3. core/loop_engine.py

```python
from dataclasses import dataclass, field
from traceweaver.core.protocols import Message
import time

@dataclass
class LoopState:
    messages: list[Message] = field(default_factory=list)
    events: list = field(default_factory=list)
    schema_retries: int = 0
    seen_calls: dict = field(default_factory=dict)
    t0: float = 0.0
    def append_message(self, msg): self.messages.append(msg)
    def append_event(self, ev): self.events.append(ev)

class LoopEngine:
    def create_state(self, task, user_request: str) -> LoopState:
        return LoopState(messages=[Message(role="user", content=user_request)], t0=time.perf_counter())
```

### 4. core/schema_guard.py

```python
import jsonschema
from typing import Tuple

class SchemaGuard:
    def check(self, final_json: dict | None, schema: dict) -> Tuple[bool, str | None]:
        if final_json is None:
            return False, "No JSON"
        required = schema.get("required", [])
        missing = [k for k in required if k not in final_json]
        if missing:
            return False, f"Missing: {missing}"
        try:
            jsonschema.validate(instance=final_json, schema=schema)
            return True, None
        except jsonschema.ValidationError as e:
            return False, e.message
```

### 5. core/tool_dispatcher.py

```python
from traceweaver.core.protocols import ToolCall, ToolContext
from traceweaver.core.trace import ToolExecution
import json

class ToolDispatcher:
    def __init__(self, tools: list):
        self.tools = {t.spec.name: t for t in tools}
        self.tool_list = tools

    def dispatch(self, calls: list[ToolCall], ctx: ToolContext, forbid: tuple, seen: dict) -> list[ToolExecution]:
        executions = []
        for call in calls:
            if call.name in forbid:
                executions.append(ToolExecution(call=call, ok=False, error=f"forbidden: {call.name}"))
                continue
            if call.name not in self.tools:
                executions.append(ToolExecution(call=call, ok=False, error=f"unknown: {call.name}"))
                continue
            key = (call.name, json.dumps(call.arguments, ensure_ascii=False, sort_keys=True))
            if key in seen:
                executions.append(ToolExecution(call=call, ok=False, error=f"duplicate: round {seen[key]}"))
                continue
            seen[key] = len(executions)
            try:
                result = self.tools[call.name].run(ctx, **call.arguments)
                executions.append(ToolExecution(call=call, ok=True, data=result.data, refs=result.refs, truncated=result.truncated))
            except Exception as e:
                executions.append(ToolExecution(call=call, ok=False, error=f"{type(e).__name__}: {e}"))
        return executions
```

---

## 阶段 B: ToolSpec Pydantic 化

所有工具重写示例:

```python
from pydantic import BaseModel, Field
from typing import Annotated
from traceweaver.core.protocols import Tool, ToolContext, ToolResult, ToolSpec

class GetUETimelineArgs(BaseModel):
    ran_ue_ngap_id: Annotated[str | None, Field(description="RAN UE ID")] = None
    amf_ue_ngap_id: Annotated[str | None, Field(description="AMF UE ID")] = None
    limit: Annotated[int, Field(ge=1, le=200)] = 50

class GetUETimelineTool(Tool):
    spec = ToolSpec.from_pydantic(GetUETimelineArgs, name="get_ue_timeline", description="Return UE timeline")
    def run(self, ctx: ToolContext, **kwargs) -> ToolResult:
        args = GetUETimelineArgs.model_validate(kwargs)
        # use args.ran_ue_ngap_id, args.limit
        return ToolResult(data={...})
```

---

## 阶段 C: summarize_capture 纯化

删除 `likely_*`, `verdict_guardrails`。信号字典:

```python
signals = {
    "pfcp_setup_request_count": pfcp_setup_reqs,
    "pfcp_setup_response_count": pfcp_setup_resps,
    "pfcp_setup_unbalanced": pfcp_setup_reqs > 0 and pfcp_setup_reqs != pfcp_setup_resps,
    "sbi_http_5xx_count": http_5xx_count,
    "sbi_http_4xx_count": http_4xx_count,
    "has_deregistration": has_deregistration,
    "has_deactivation": has_deactivation,
    "retry_pattern_present": retry_pattern_present,
    "pdu_session_setup_started": pdu_setup_started,
    "pdu_session_setup_completed": pdu_setup_completed,
}

capture_findings = [
    {"signal": "PFCP_SETUP_UNBALANCED", "details": {"req": 5, "resp": 3}},
    {"signal": "PDU_SESSION_REJECT", "details": {"count": 2}},
    {"signal": "DEREGISTRATION", "details": {}}},
]
```

system.md 新增 Signal-to-Action 章节，LLM 自己判断。

---

## 阶段 D: 记录-回放

```python
from traceweaver.core.protocols import Intelligence, IntelligenceRequest, IntelligenceResponse
from pathlib import Path
import yaml

class RecordReplayIntelligence(Intelligence):
    def __init__(self, inner: Intelligence | None, path: Path, mode: str):
        self.inner = inner
        self.path = path
        self.mode = mode
        self._recording = []
        self._idx = 0
        if mode == "replay":
            self._recording = yaml.safe_load(path.read_text())

    def think(self, req: IntelligenceRequest) -> IntelligenceResponse:
        if self.mode == "replay":
            turn = self._recording[self._idx]
            self._idx += 1
            return IntelligenceResponse(**turn["response"])
        resp = self.inner.think(req)
        if self.mode == "record":
            self._recording.append({"request": req.model_dump(), "response": resp.model_dump()})
            self.path.write_text(yaml.safe_dump(self._recording))
        return resp
```

---

## 删除的文件

- `core/source/pcap.py` → `builtin/sources/pcap.py`
- `core/source/fake.py` → `builtin/sources/fake.py`
- `core/source/enrich.py` → `builtin/sources/enriched.py`
- `core/tools/builtin/` → `builtin/tools/`
- `core/knowledge/file_store.py` → `builtin/knowledge/file_store.py`
- `core/source/registry.py` 中的自动注册逻辑 → CLI 显式注册
- `core/tools/registry.py` 中的 `_coerce` → 删除，Pydantic 处理
- `summarize_capture.py` 中的 `likely_*` 和 `verdict_guardrails` → 删除

---

## 修改的 import (批量替换)

```python
# 旧 (失效)
from traceweaver.core.source import PcapSource, FakeSource
from traceweaver.core.tools.builtin import QueryRecordsTool
from traceweaver.core.knowledge import FileKnowledgeStore

# 新
from traceweaver.builtin.sources.pcap import PcapSource
from traceweaver.builtin.sources.fake import FakeSource
from traceweaver.builtin.tools.query_records import QueryRecordsTool
from traceweaver.builtin.knowledge.file_store import FileKnowledgeStore
from traceweaver.builtin import register_builtin_sources, register_builtin_tools
```

---

## CLI 启动显式注册

```python
from traceweaver.builtin import register_builtin_sources, register_builtin_tools
from traceweaver.core.protocols import SourceRegistry

def run(args):
    registry = SourceRegistry()
    register_builtin_sources(registry)
    # ... 后续使用 registry
    
    tool_registry = ToolRegistry()
    register_builtin_tools(tool_registry)
    # ... 加载 profile tools
```

---

执行即最终状态。
