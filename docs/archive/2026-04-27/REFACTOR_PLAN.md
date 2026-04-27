> 📌 **此文档已于 2026-04-27 归档**。当前主路线图见 [`ROADMAP.md`](../../../ROADMAP.md)（项目根）。
>
> **落地状态**：
> - ✅ 阶段 A（纯化 core/，迁出 PcapSource/FileKnowledgeStore/builtin tools 到 `builtin/`）已完成
> - ✅ 阶段 C（删除 `summarize_capture` 的 `likely_*` 与 `verdict_guardrails`）已完成
> - ❌ 阶段 B（ToolSpec 自动从 Pydantic 生成）未做，见 ROADMAP 持续改进项
> - ❌ 阶段 D（Record-Replay 系统）未做，见 ROADMAP M7'
> - ❌ 阶段 E（Profile 贡献点机制）的部分内容已被 ROADMAP M5'（entry_points）取代
> - ❌ 阶段 F（Kernel 拆分）未做，且暂不在 ROADMAP 中——当前 kernel 体量可控
>
> 当本文档与 ROADMAP 冲突时，以 ROADMAP 为准。

---

# TraceWeaver 重构计划 v1.0

> 基于架构审视结果，针对 core/ 边界失守、工具 schema 硬编码、smoke 测试外部依赖等问题的完整修改路线图。
> **核心原则**：保持 LLM-first + Profile 即插即用的设计意图，让 `core/` 真正变成纯内核。

---

## 依赖关系总览

```
阶段 A (纯化 core/) ───────────────────────────────────────────┐
    │                                                         │
    ├─→ 阶段 B (ToolSpec 自动生成) ──→ 阶段 C (summarize 拆分) │
    │                                                         │
    ├─→ 阶段 D (记录-回放系统) ────────────────────────────────┤
    │                                                         │
    └─→ 阶段 E (Profile 贡献点) ──→ 阶段 F (Kernel 拆分)     │
                                                                │
                              ↓                                 │
                        M4/M5/M6 落地                           │
```

---

## 阶段 A：纯化 core/ —— 抽离所有具体实现到 builtin/

### 当前问题
core/ 当前承载了三种不应属于"内核"的代码：
- `PcapSource`（依赖 tshark、subprocess、TSV 解析）
- `FileKnowledgeStore`（依赖文件系统、markdown 解析）
- `query_records` / `get_records_around`（依赖具体 SourceHandle 实现）

这导致 core 无法在不安装 Wireshark 的环境中运行单元测试，且每新增一种数据源（LogSource）就必须修改 core 的 import。

### 目标
core/ 只保留纯协议、值对象和 AgentKernel 引擎。不依赖文件系统、网络、subprocess、importlib。

### 具体步骤

#### A1. 创建 `traceweaver/builtin/` 包
```
builtin/
├── __init__.py              # 注册 builtin sources/tools/knowledge
├── sources/
│   ├── __init__.py
│   ├── pcap.py              # 从 core/source/pcap.py 迁移
│   └── registry.py          # builtin source 注册表（PcapSource、FakeSource）
├── tools/
│   ├── __init__.py
│   ├── query_records.py     # 从 core/tools/builtin/ 迁移
│   ├── get_records_around.py
│   └── search_knowledge.py
└── knowledge/
    ├── __init__.py
    └── file_store.py        # 从 core/knowledge/file_store.py 迁移
```

#### A2. 改造 `core/source/` 为纯协议层
- `base.py`：保留 `Record`, `SourceSpec`, `SourceHandle(ABC)`, `Source(ABC)`
- 删除 `pcap.py`, `fake.py`, `enrich.py`（迁移到 builtin/）
- `enrich.py` 中的 `EnrichedSourceHandle` 保留为协议层（移到 `core/source/base.py`），但实现移到 `builtin/sources/enriched.py`
- `registry.py`：改为纯注册接口，不内置任何 source 实例

#### A3. 改造 `core/tools/` 为纯协议层
- `base.py`：保留 `ToolSpec`, `ToolContext`, `ToolResult`, `Tool(ABC)`
- `registry.py`：保留注册/分发逻辑
- 删除 `builtin/` 子目录（全部迁到 `builtin/tools/`）
- `loader.py`：保留动态 import 逻辑（core 需要这个），但默认不加载任何工具

#### A4. 改造 `core/knowledge/` 为纯协议层
- `base.py`：保留 `KnowledgeStore(ABC)`, `KnowledgeHit`
- 删除 `file_store.py`（迁移到 `builtin/knowledge/`）

#### A5. 改造 CLI 入口
- `cli/analyze.py` 中显式 `from traceweaver.builtin import register_builtin_sources, register_builtin_tools`
- 分析命令启动时主动注册 builtin 组件

### 验收标准
- [ ] `import traceweaver.core.kernel` 不需要 tshark、不需要文件系统
- [ ] `pytest tests/core/` 可在无 Wireshark 环境中通过
- [ ] `pytest tests/builtin/` 需要 Wireshark，单独标记
- [ ] 删除 `core/` 下所有 `subprocess`、`shutil.which`、`pathlib.Path` 的 import

### 工作量估算：1.5 天

---

## 阶段 B：ToolSpec 自动生成 —— 消除手动维护负担

### 当前问题
每个工具的 `parameters_schema` 都是手动编写的 JSON Schema，例如：
```python
spec = ToolSpec(
    name="get_ue_timeline",
    parameters_schema={
        "type": "object",
        "properties": {
            "ran_ue_ngap_id": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 200},
        },
        "required": [],
    },
)
```

工具参数变更时 schema 与函数签名不同步。`summarize_capture` 因为无参数而避开了这个问题，但其他 5 个工具每个都有 20-50 行 schema。

### 目标
从 `Tool.run()` 的函数签名自动生成 OpenAI-compatible JSON Schema。

### 具体步骤

#### B1. 引入 `pydantic` 作为工具参数描述方式
```python
from pydantic import BaseModel, Field
from typing import Annotated

class GetUETimelineArgs(BaseModel):
    ran_ue_ngap_id: Annotated[str | None, Field(description="UE identifier")] = None
    amf_ue_ngap_id: Annotated[str | None, Field(description="AMF UE identifier")] = None
    limit: Annotated[int, Field(ge=1, le=200, description="Max events to return")] = 50

class GetUETimelineTool(Tool):
    spec = ToolSpec.from_model(GetUETimelineArgs, description="...")

    def run(self, ctx: ToolContext, **kwargs) -> ToolResult:
        args = GetUETimelineArgs.model_validate(kwargs)
        # 使用 args.ran_ue_ngap_id 等
```

#### B2. `ToolSpec.from_callable()` 辅助方法
```python
class ToolSpec(BaseModel):
    @classmethod
    def from_callable(cls, fn: Callable, description: str) -> "ToolSpec":
        """从函数签名 + Annotated 生成 JSON Schema"""
        schema = generate_schema_from_signature(fn)
        return cls(name=fn.__name__, description=description, parameters_schema=schema)
```

使用 `inspect.signature` + `typing.get_type_hints` 提取参数名、类型、默认值、`Field` 的 `ge/le/description`。

#### B3. 兼容层：支持现有手动 schema
新增 `ToolSpec.from_manual_schema(name, description, parameters_schema)` 作为过渡。已有的 6 个工具可以逐步迁移。

#### B4. Registry 改造
`_validate_arguments` 利用 Pydantic 的 `model_validate` 替代手写 coerce 逻辑：
```python
# 之前：手动 coerce string -> int/bool
# 之后：
if hasattr(tool.spec, "_args_model"):
    validated = tool.spec._args_model.model_validate(arguments)
    return validated.model_dump()
```

### 验收标准
- [ ] `SummarizeCaptureTool` 迁移到自动 schema（零参数，验证边界情况）
- [ ] `GetUETimelineTool` 迁移后，schema 与原 hand-written schema 等价（diff 对比）
- [ ] `_coerce` 方法行数减少 50% 以上
- [ ] 新增工具时只需写 Pydantic Model，不需要写 JSON Schema

### 工作量估算：1 天

---

## 阶段 C：重构 summarize_capture —— 分离信号提取与业务推断

### 当前问题
`summarize_capture.py` 350 行硬编码了 5GC 业务逻辑（PFCP balance、SBI HTTP 4xx、retry pattern、deregistration flow）。这违反了"工具不做诊断判断"的红线。

**问题的本质**：不是"工具不能提取信号"，而是"工具不能把信号包装成带有倾向性的推断"。`likely_pfcp_failure`、`likely_sbi_failure` 这些命名本身就是诊断结论。

### 目标
将工具拆分为两层：
1. **信号层（Signal Layer）**：纯事实计数（`pfcp_setup_request_count`, `http_5xx_count`）
2. **推断层（Inference Layer）**：LLM 通过 system prompt 里的推理规则，自行组合信号得出结论

这样当新增 PFCP 消息类型时，只需改字段映射；当诊断规则变化时，只需改 prompt。

### 具体步骤

#### C1. 重命名所有 `likely_*` 为中性 `has_*` / `count_*`
```python
# 之前
"likely_pfcp_failure": pfcp_setup_reqs > 0 and pfcp_setup_reqs != pfcp_setup_resps,
"likely_sbi_failure": has_http_5xx or has_http_4xx or ...,

# 之后
"pfcp_setup_unbalanced": pfcp_setup_reqs > 0 and pfcp_setup_reqs != pfcp_setup_resps,
"sbi_http_4xx_count": nsmf_pdu_http_4xx_count + nudm_sm_data_http_4xx_count,
"has_retry_pattern": retry_pattern_present,
```

#### C2. 删除 `verdict_guardrails` 列表
当前 verdict_guardrails 是"人话版的规则"（"PFCP session setup requests are not balanced..."），这本质是用规则语言教 LLM 诊断。改为在 system prompt 中写推理规则：
```markdown
### 信号解读指南
- 当 `pfcp_setup_unbalanced == true` 时，你必须调用 `get_pfcp_exchanges` 才能下结论。
- 当 `sbi_http_4xx_count > 0` 时，优先调用 `get_sbi_calls`。
```

#### C3. 保留 `capture_findings` 但改为 LLM 可见的"原始信号摘要"
```python
capture_findings = [
    {"type": "signal", "name": "PFCP_SETUP_UNBALANCED", "details": {"requests": 5, "responses": 3}},
    {"type": "signal", "name": "SBI_HTTP_4XX", "details": {"count": 2, "paths": ["/nsmf-pdusession/..."]}},
]
```

#### C4. 将 `summarize_capture` 的推断逻辑迁移到 `system.md` 的 workflow 章节
新增一节 "Signal-to-Action Mapping"，明确每种信号对应的强制工具调用。

### 验收标准
- [ ] `summarize_capture.py` 删除所有 `likely_*` 键
- [ ] `verdict_guardrails` 列表为空或删除
- [ ] system.md 新增 "Signal-to-Action Mapping" 章节
- [ ] M3 smoke 9/9 通过（验证 LLM 能从纯信号正确推理）
- [ ] `_m3_accuracy.py` 的 accuracy 指标不下降

### 工作量估算：1 天

---

## 阶段 D：LLM 记录-回放系统 —— 解除 smoke test 外部依赖

### 当前问题
`scripts/run_m3_smoke.py` 必须连接 LM Studio（`http://127.0.0.1:1234/v1`）。这导致：
- CI 无法运行
- 回归测试耗时 10-30 分钟（取决于 GPU 速度）
- 无法在无网络/无 GPU 环境验证

### 目标
引入 `RecordReplayIntelligence`，将 LLM 对话完整序列化为 YAML/JSON，支持 deterministic 回放。

### 具体步骤

#### D1. `RecordIntelligence` 包装器
```python
class RecordIntelligence(Intelligence):
    def __init__(self, inner: Intelligence, recording_path: Path | None):
        self.inner = inner
        self.recording = []
        self.path = recording_path

    def think(self, request: IntelligenceRequest) -> IntelligenceResponse:
        if self._has_recording_for(request):
            return self._replay(request)
        resp = self.inner.think(request)
        self._record(request, resp)
        return resp
```

#### D2. 录制格式（YAML）
```yaml
# recordings/m3_01_registration_success.yaml
- turn: 1
  request:
    system_prompt: "..."
    messages: [...]
    tools: [...]
  response:
    kind: tool_calls
    tool_calls:
      - name: summarize_capture
        arguments: {}
    reasoning: ""

- turn: 2
  request:
    system_prompt: "..."
    messages: [...previous turn results...]
  response:
    kind: final
    final_text: '{"verdict": "success", ...}'
    final_json:
      verdict: success
```

#### D3. 确定性匹配键
录制匹配不应比较完整 messages（因为 tool results 可能变化），而是匹配：
- system prompt hash
- user request 文本
- tool_calls 列表（name + arguments）

当 LLM 选择了不同的工具或参数时， recording miss →  fallback 到 real LLM → 报错提示需要重新录制。

#### D4. 集成到 smoke scripts
```bash
# 录制模式（人工跑一次）
python scripts/run_m3_smoke.py --model openai/qwen/qwen3.5-9b --record

# 回放模式（CI 使用）
python scripts/run_m3_smoke.py --replay recordings/
```

#### D5. 测试改造
- `tests/core/kernel/test_kernel_loop.py`：用 FakeIntelligence（已有）
- `tests/profiles/open5gs_5gc/test_smoke_regression.py`：用 RecordReplayIntelligence
- `tests/builtin/`：纯单元测试，不涉及 LLM

### 验收标准
- [ ] `pytest tests/smoke/ --replay` 在无 LLM 环境下 30 秒内跑完 9 个 case
- [ ] 录制文件大小 < 1MB per case（压缩后）
- [ ] 回放准确率：tool_calls 匹配率 100%，final_json 准确率 ≥ M3 基线
- [ ] README 更新：说明如何录制和回放

### 工作量估算：1.5 天

---

## 阶段 E：Profile 贡献点机制 —— VS Code 扩展模式

### 当前问题
Profile 通过 YAML 声明 tools/knowledge/source_config，但缺乏：
1. **激活条件**：什么场景下该 profile 被自动选中？
2. **贡献点类型**：只有 tools，没有"transforms"、"views"、"diagnosis_formatters"
3. **冲突解决**：同名 tool 注册时的覆盖策略不明确

### 目标
引入 `contributes` 机制，让 profile 像 VS Code 扩展一样声明能力。

### 具体步骤

#### E1. 扩展 `profile.yaml` schema
```yaml
name: open5gs_5gc
contributes:
  sources:
    - kind: pcap
      display_filter: "ngap || nas-5gs || http2 || pfcp"
      confidence: 0.8   # 当 capture 匹配此 filter 时，该 profile 的推荐分数

  tools:
    - module: traceweaver.profiles.open5gs_5gc.tools.summarize_capture
      class: SummarizeCaptureTool
      # 不需要 parameters_schema，因为阶段 B 自动生成

  knowledge:
    - file: knowledge/5gmm_causes.md
      tags: ["nas", "5gmm", "cause"]

  # 新增：prompts 也可以作为贡献点
  prompts:
    - name: system
      file: prompts/system.md
      for_verdicts: ["success", "failure", "unclear"]

  # 新增：激活规则
  activation:
    - when: source.kind == "pcap"
      and: capture.protocol_distribution.ngap > 0
      or: capture.protocol_distribution.pfcp > 0
```

#### E2. Profile Capability Score
CLI 加载 capture 后，扫描所有 profile，计算匹配分数：
```python
def score_profile(profile: Profile, source_handle: SourceHandle) -> float:
    md = source_handle.metadata()
    score = 0.0
    for rule in profile.activation_rules:
        score += evaluate(rule, md)
    return min(score, 1.0)
```
`traceweaver analyze capture.pcap` 不传 `--profile` 时，自动选择最高分 profile（分数>0.5），或提示用户选择。

#### E3. Tool 注册冲突策略
```python
registry.register(tool, source="profile:open5gs_5gc", priority=100)
# 后注册的同名 tool：
# - 如果 priority 更高：覆盖
# - 如果 priority 相同：报错
# - 如果 source 是 "builtin"：默认 priority=50
```

### 验收标准
- [ ] `profile.yaml` 新增 `contributes` 顶层键，向后兼容旧格式
- [ ] `traceweaver analyze capture.pcap`（无 --profile）能自动推荐 open5gs_5gc
- [ ] 两个 profile 声明同名 tool 时，priority 机制生效
- [ ] docs/guides/writing-a-profile.md 更新

### 工作量估算：1 天

---

## 阶段 F：AgentKernel 职责拆分 —— 循环/验证/格式化分离

### 当前问题
`AgentKernel` 500 行承担了：
- 对话循环管理（`_LoopState`）
- tool dispatch（`_handle_tool_calls`）
- schema 校验（`_schema_validate_full`, `_schema_missing_keys`）
- 错误格式化（`_tool_result_to_text`）
- 重复调用检测（`_seen_key_round`）

这违反了单一职责原则。当需要支持流式输出、并行 tool calling、或中断/恢复时，当前结构难以扩展。

### 目标
将 AgentKernel 拆分为 3 个可替换组件：
1. **LoopEngine**：只管理对话轮次和 tool dispatch
2. **SchemaGuard**：独立验证 final answer，注入 retry prompt
3. **OutputFormatter**：渲染 tool results、错误消息、trace 事件

### 具体步骤

#### F1. 提取 `SchemaGuard`
```python
class SchemaGuard:
    def __init__(self, schema: dict | None, max_retries: int = 1):
        self.schema = schema
        self.max_retries = max_retries

    def check(self, text: str | None, json: dict | None) -> tuple[bool, str | None]:
        """返回 (is_valid, error_message_for_llm)"""
        ...
```

#### F2. 提取 `ToolDispatcher`
```python
class ToolDispatcher:
    def __init__(self, registry: ToolRegistry, ctx: ToolContext):
        ...

    def dispatch(self, tool_calls: list[ToolCall], task: TaskSpec) -> list[ToolExecution]:
        """执行全部 tool calls，处理重复调用、forbidden tools、未知 tools"""
        ...
```

#### F3. 简化 `AgentKernel`
```python
class AgentKernel:
    def __init__(self, intelligence: Intelligence, registry: ToolRegistry,
                 loop_engine: LoopEngine | None = None,
                 schema_guard: SchemaGuard | None = None):
        ...
```
默认提供 `StandardLoopEngine`，但允许替换为：
- `StreamingLoopEngine`（支持 SSE 输出）
- `ParallelToolLoopEngine`（支持并行 tool calls）

#### F4. 状态持久化接口
```python
class LoopState(ABC):
    @abstractmethod
    def append_message(self, msg: Message) -> None: ...
    @abstractmethod
    def append_event(self, ev: TraceEvent) -> None: ...
    @abstractmethod
    def dump(self) -> dict: ...
    @abstractmethod
    def load(self, snapshot: dict) -> None: ...
```
支持中断后恢复（MCP server 场景）。

### 验收标准
- [ ] `AgentKernel` 行数 < 250 行
- [ ] `SchemaGuard` 独立单元测试覆盖 100%
- [ ] `ToolDispatcher` 独立单元测试覆盖 100%
- [ ] `LoopEngine` 接口支持序列化/反序列化（为 M7 MCP server 做准备）

### 工作量估算：1.5 天

---

## 总工作量与优先级

| 阶段 | 工作量 | 优先级 | 阻塞后续？ |
|------|--------|--------|----------|
| A 纯化 core/ | 1.5 天 | **P0** | 阻塞 B/C/D/E/F |
| B ToolSpec 自动生成 | 1 天 | **P0** | 阻塞 C |
| C summarize_capture 拆分 | 1 天 | **P0** | 阻塞 M3 regression |
| D 记录-回放系统 | 1.5 天 | **P0** | 无阻塞，但极大提升开发效率 |
| E Profile 贡献点 | 1 天 | P1 | 阻塞 M4 Extension |
| F Kernel 拆分 | 1.5 天 | P1 | 阻塞 M7 MCP Server |

**建议执行顺序**：
```
Week 1: A → B → C（core 稳定化）
Week 2: D → E（测试与扩展机制）
Week 3: F（为 M7 做准备，可延后）
```

---

## 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| C 阶段修改 system prompt 后 LLM 表现下降 | M3 smoke 失败 | 在 C 阶段同时跑新旧 prompt，对比 accuracy；保留旧 prompt 做 fallback |
| A 阶段迁移引入 import 路径断裂 | 现有测试失败 | 每迁移一个模块，立即跑 `pytest` 验证；使用 `git mv` 保留历史 |
| D 阶段录制文件过大 | 仓库膨胀 | 录制文件放入 `.gitattributes` + LFS；或放入 `tests/recordings/` 但不 commit，由 CI 缓存 |

---

## 即时可开始的下一步

如果你同意这个计划，第一个可执行的步骤是：

1. **创建 `traceweaver/builtin/` 目录骨架**
2. **迁移 `core/source/pcap.py` → `builtin/sources/pcap.py`**
3. **修改 `core/source/__init__.py` 不再默认导出 PcapSource**

要我直接生成阶段 A 的代码补丁吗？
