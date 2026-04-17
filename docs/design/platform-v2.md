# TraceWeaver v2 平台架构设计

**状态**：设计中，准备执行
**基线模型**：`ollama/qwen3.5:9b`（要求稳定 tool calling）
**目标交付时间**：约 7 周（M1–M5 分阶段）

---

## 0. 文档地图

本文档定义 v2 架构。相关文档：

- `docs/guides/python-packaging-profiles.md` — Profile 如何打成 pip 包分发
- `scripts/validate_tool_calling.py` — 9B 基线 tool calling 可用性验证脚本
- `archive/v1/README.md` — v1 归档说明
- `docs/archive/plan/` — v1 阶段的历史规划文档（仅供参考）

---

## 1. 为什么需要 v2

v1 试图用 LLM 做 5GC 诊断，但结构上把 LLM 放在规则链路末端当"解释器"：

```
pcap → tshark → 规则抽信号 → 规则诊断 → LLM 翻译成自然语言
```

这带来三个结构性问题：

1. **LLM 看不到原始数据**，只能看到规则预消化后的 signals
2. **规则可以覆盖 LLM 的判断**（`_apply_visibility_constraints`）
3. **加新协议 = 重写 1800+ 行 profile 代码**，不是平台

v2 把 LLM 提升为**唯一的诊断主体**，把平台做成**分层可插拔**的基础设施，让任何行业/协议都能通过注入自己的内容来使用。

## 2. 总体目标

一个基于 tshark、LLM 驱动、可插拔、越用越好用的 pcap + 日志分析平台。

7 项核心能力：

| # | 能力 | 实现层 |
|---|------|--------|
| 1 | tshark 基础抓包分析 | Layer 0: Sources |
| 2 | 协议可配（声明式） | Layer 1: Profiles |
| 3 | 分析工具可插拔（用户扩展） | Layer 2: Tools |
| 4 | 主流 agent 生态对接（MCP） | Layer 5: Interfaces |
| 5 | LLM 多后端（本地/云/外部 agent） | Layer 4: Intelligence |
| 6 | 自我进化（案例库） | Case Memory（贯穿层） |
| 7 | pcap + 日志联合分析 | Layer 0: Sources（composed） |

## 3. 架构总图

```
┌──────────────────────────────────────────────────────────────────┐
│ Layer 5: Interfaces                                              │
│   CLI  │  Python API  │  MCP Server  │  HTTP API                 │
│   (同一份内核，不同壳)                                            │
└──────────────────────────────────────────────────────────────────┘
                                 ▲
┌──────────────────────────────────────────────────────────────────┐
│ Layer 4: Intelligence (推理后端，可插拔)                         │
│   LLMIntelligence   │  MCPAgentIntelligence  │  CustomIntelligence│
│   (litellm: ollama / openai / anthropic)    (委托外部 agent)     │
└──────────────────────────────────────────────────────────────────┘
                                 ▲
┌──────────────────────────────────────────────────────────────────┐
│ Layer 3: Agent Kernel (协议无关的推理内核)                       │
│   Tool calling loop  │  Budget / Cache  │  Schema validation     │
│   └── 每次调用前先查 Case Memory                                  │
└──────────────────────────────────────────────────────────────────┘
                                 ▲
┌──────────────────────────────────────────────────────────────────┐
│ Layer 2: Tools (可插拔工具层)                                    │
│   Built-in tools  │  Profile tools  │  Extension tools           │
│   (core 提供)       (profile 提供)     (用户写的)                 │
└──────────────────────────────────────────────────────────────────┘
                                 ▲
┌──────────────────────────────────────────────────────────────────┐
│ Layer 1: Profiles (协议/场景包，可插拔)                          │
│   YAML 声明 + optional Python tools                               │
│   Via local directory 或 pip install                              │
└──────────────────────────────────────────────────────────────────┘
                                 ▲
┌──────────────────────────────────────────────────────────────────┐
│ Layer 0: Sources (数据源，可插拔)                                │
│   pcap source  │  log source  │  composed source (pcap + log)    │
└──────────────────────────────────────────────────────────────────┘

         ╔════════════════════════════════════════╗
         ║  Case Memory (~/.traceweaver/cases/)   ║
         ║   • 每次 --confirm 的诊断自动存         ║
         ║   • 向量化索引按 profile + 症状签名     ║
         ║   • Layer 2 暴露 find_similar_cases     ║
         ╚════════════════════════════════════════╝
```

---

## 4. 各层契约

### Layer 0: Source（数据源）

核心契约：

```python
from typing import Protocol
from pydantic import BaseModel

class SourceSpec(BaseModel):
    """实例化 Source 的参数，由 profile 或 user 填写。"""
    kind: str              # "pcap" | "log" | "composed" | ...
    uri: str               # 文件路径或数据源地址
    options: dict          # 数据源特定参数


class SourceHandle(Protocol):
    """只读的数据句柄，Tools 用它查询原始记录。"""
    kind: str
    uri: str

    def iter_records(self, filter: dict | None = None) -> Iterator[Record]: ...
    def count(self, filter: dict | None = None) -> int: ...
    def metadata(self) -> dict: ...


class Source(Protocol):
    """数据源注册点。core 通过它把 uri 变成 handle。"""
    kind: str  # 类级属性

    def ingest(self, spec: SourceSpec) -> SourceHandle: ...
```

**Record 是统一的原始记录格式**（不是 5GC 专用）：

```python
class Record(BaseModel):
    source: str        # "pcap" | "log"
    timestamp: float   # epoch 秒
    seq: int           # 源内自增（pcap 里 = frame.number，log 里 = line number）
    key: str           # 关联键（pcap 里 = tcp.stream 或 5-tuple；log 里 = trace_id/request_id）
    fields: dict       # 协议/结构化字段
    raw: str           # 原始行/info 列
```

三个 Source 实现（M1 先做 pcap）：

1. `PcapSource`：基于 tshark，接收 `display_filter`, `decode_as`, `fields` 参数
2. `LogSource`（M3）：接收 `format`(json/syslog/regex), `time_field`, `key_field`
3. `ComposedSource`（M3）：包装若干 `Source`，按时间戳排序统一迭代，附加 `source` 标识

### Layer 1: Profile（场景包）

Profile 的物理形态：一个目录。

```
my-profile/
├── profile.yaml         # 声明式配置（必需）
├── prompts/
│   └── system.md        # LLM system prompt（必需）
├── tools/               # Profile 私有工具实现（可选）
│   └── __init__.py
├── knowledge/           # RAG 语料（可选）
│   └── *.md
└── schema/              # 附加的自定义 schema（可选）
```

`profile.yaml` 规范：

```yaml
name: open5gs_5gc                    # 唯一标识
version: 1.0
display_name: "Open5GS 5G Core"
description: "5G Core network fault diagnosis"

# 声明这个 profile 能处理的 source 类型
applies_to_sources: [pcap, composed]

# ============================================
# Source 配置：如何从原始文件抽取记录
# ============================================
source_config:
  pcap:
    display_filter: "ngap || http2 || pfcp"
    decode_as:
      - "tcp.port==7777,http2"
    fields:
      - frame.number
      - frame.time_epoch
      - frame.protocols
      - ngap.RAN_UE_NGAP_ID
      - ngap.AMF_UE_NGAP_ID
      # ... 完整字段清单见 archive/v1 抽取器
    # key_strategy 决定 Record.key 怎么算
    key_strategy:
      mode: derived_fields
      fields: [ngap.RAN_UE_NGAP_ID, ngap.AMF_UE_NGAP_ID]

# ============================================
# Scope 配置：怎么把记录切成分析单元
# ============================================
scope:
  strategy: group_by_fields
  primary_key: [ngap.RAN_UE_NGAP_ID, ngap.AMF_UE_NGAP_ID]
  # scope 内子结构（optional）
  sub_scopes:
    - name: pdu_session
      strategy: group_by_fields
      primary_key: [nas_5gs.sm.pdu_session_id]

# ============================================
# LLM 配置
# ============================================
llm:
  system_prompt_file: prompts/system.md
  max_rounds: 5
  response_schema_file: schema/diagnosis.json
  # 可选：推荐模型（用户可覆盖）
  recommended_model: "ollama/qwen3.5:9b"

# ============================================
# 工具声明
# ============================================
tools:
  # profile 自带工具
  - module: my_profile.tools.sbi
    class: GetSBICalls
  - module: my_profile.tools.pfcp
    class: GetPFCPMessages
  - module: my_profile.tools.timeline
    class: GetTimeline

# ============================================
# 知识库（可选）
# ============================================
knowledge:
  - file: knowledge/5gmm_cause_codes.md
    tags: [cause_code, registration]
  - file: knowledge/open5gs_architecture.md
    tags: [architecture]
```

**Profile 加载优先级**（C 选项实现）：

1. **本地目录**（优先级 B，M1 实现）：扫描 `~/.traceweaver/profiles/*/profile.yaml`，以及 `$TRACEWEAVER_PROFILES_PATH` 指向的目录
2. **pip 安装的包**（优先级 A，M2 实现）：扫描 `traceweaver.profiles` entry_point

**扫描冲突策略**：同名 profile 以本地目录为准（方便用户覆盖测试）。

### Layer 2: Tool（插件工具）

契约：

```python
class ToolSpec(BaseModel):
    """LLM 看到的工具规范，对应 OpenAI tool calling 格式。"""
    name: str                       # 必须全平台唯一
    description: str                # LLM 决定用不用的关键
    parameters: dict                # JSON Schema
    applies_to: list[str] = []      # 限定 profile；空=全部
    requires_sources: list[str] = []# 需要哪些 source 类型


class ToolContext(BaseModel):
    """工具运行时能访问的只读环境。"""
    source_handle: SourceHandle
    scope: ScopeHandle              # 当前分析 scope
    profile_name: str
    tool_history: list[ToolInvocation]  # 已调用过的工具（只读）
    knowledge_store: KnowledgeStore     # 让工具能查 profile 知识库

    class Config:
        frozen = True


class ToolResult(BaseModel):
    """工具返回格式。不允许包含判断性字段。"""
    data: dict                      # 事实数据（必须可 JSON 序列化）
    refs: list[str] = []            # 证据引用（frame numbers / log line ids）
    warnings: list[str] = []        # 采集/处理类警告，不是诊断判断
    truncated: bool = False         # 如果因大小限制截断了


class Tool(Protocol):
    spec: ToolSpec
    def run(self, ctx: ToolContext, **kwargs) -> ToolResult: ...
```

**禁止在 `ToolResult.data` 中返回 `verdict`, `failure_point`, `root_cause`, `confidence`
这类字段**，否则用户可以绕过 LLM 写规则引擎。core 在运行时会 schema 校验拒绝。

**工具三种来源**（LLM 看不到来源区别）：

- **Built-in**（core 提供）：
  - `query_records(filter, fields, limit)` — 受限 tshark/log 查询
  - `get_records_around(seq, before, after)` — 查上下文
  - `get_source_metadata()` — pcap 元信息、时间范围
  - `find_similar_cases(symptoms)` — 案例库检索（M4）
  - `search_knowledge(query, tags)` — profile 知识库检索

- **Profile tools**：profile 自带，在 `profile.yaml` 声明
- **Extension tools**：用户写的，用户通过 `~/.traceweaver/extensions/tools.yaml` 注册：

  ```yaml
  # ~/.traceweaver/extensions/tools.yaml
  extensions:
    - module: my_plugins.correlate_kpi
      class: CorrelateKPI
      applies_to: [open5gs_5gc]
    - module: my_plugins.compare_baseline
      class: CompareBaseline
  ```

  或者通过 pip 包 entry_points 注册（M2）：

  ```toml
  [project.entry-points."traceweaver.tools"]
  correlate_kpi = "my_plugins.correlate_kpi:CorrelateKPI"
  ```

**工具组装流程**：

```
profile 被加载
  ├── 读 profile.yaml 里的 tools[] → ProfileTools
  ├── 扫描 built-in tools → BuiltinTools
  └── 扫描 extension tools → ExtensionTools
       ├── 过滤 applies_to 不匹配的
       └── 过滤 requires_sources 无法满足的

最终给 LLM 的工具列表 = Builtin ∪ Profile ∪ ApplicableExtension
（如果总数 > 8，按 profile 配置的优先级裁剪）
```

### Layer 3: Agent Kernel（推理内核）

Agent Kernel 不知道"5GC"是什么，它只做一件事：把工具列表喂给 Intelligence，让它循环，直到结论。

```python
class AgentKernel:
    def __init__(
        self,
        intelligence: Intelligence,
        tools: list[Tool],
        system_prompt: str,
        response_schema: dict,
        max_rounds: int = 5,
        budget: AgentBudget = AgentBudget(),
    ):
        ...

    def run(self, user_request: str, context: AgentContext) -> AgentResult:
        """
        标准 tool calling loop:
        1. 把 system_prompt + user_request 发给 intelligence
        2. intelligence 要么返回 tool_calls，要么返回 final output
        3. 如果是 tool_calls:
           - 参数校验（JSON Schema）
           - 幂等缓存（同参数同工具命中直接返回）
           - 配额检查（每轮上限、会话上限）
           - 执行工具 → ToolResult
           - 结果 token 预算检查，超了截断
           - 把 ToolResult 作为 tool_result 消息加入对话
        4. 回到步骤 2，直到 intelligence 输出 final 或达到 max_rounds
        5. 最终输出按 response_schema 校验，失败则重试 1 次
        6. 返回 AgentResult（含完整调查轨迹）
        """
```

**不做的事**（红线）：

- ❌ 内核不看 tool 返回的 `data` 做任何判断
- ❌ 内核不改 intelligence 给出的结论
- ❌ 内核不做 rule fallback（9B 输出不合 schema 就重试 1 次，再失败就返回 `INCONCLUSIVE + error_detail`）
- ❌ 内核不根据 verdict 决定下一步（那是 intelligence 的事）

### Layer 4: Intelligence（推理后端）

```python
class IntelligenceRequest(BaseModel):
    system_prompt: str
    messages: list[Message]         # 已有对话（含工具结果）
    tools: list[ToolSpec]           # 可用工具
    response_schema: dict | None    # 最终输出 schema


class IntelligenceResponse(BaseModel):
    kind: Literal["tool_calls", "final"]
    tool_calls: list[ToolCall] = []
    final: dict | None = None       # 匹配 response_schema
    reasoning: str | None = None    # 可选推理文本


class Intelligence(Protocol):
    name: str
    def think(self, req: IntelligenceRequest) -> IntelligenceResponse: ...
```

**M1 只实现 `LLMIntelligence`**（litellm 封装）。

**M5 实现 `MCPAgentIntelligence`**：这里的设计很关键——不是把 TraceWeaver 的工具调用**给** LLM，而是 **把 TraceWeaver 的工作（系统 prompt + user request + 工具列表）打包转交给一个外部 agent**。外部 agent（比如一个 Claude Code CLI、或一个自研 agent）用自己的能力完成任务，TraceWeaver 只做工具执行的"执行者"。
  对 user 来说，相当于 TraceWeaver 借用了外部 agent 的大脑。

### Layer 5: Interfaces（对外）

四种接入方式，共享同一个内核：

1. **CLI**
   ```bash
   traceweaver analyze file.pcap --profile open5gs_5gc --model ollama/qwen3.5:9b
   traceweaver analyze file.pcap --log app.log --profile open5gs_5gc  # M3
   traceweaver confirm <case-id>                                       # M4
   traceweaver serve mcp --port 8080                                   # M5
   ```

2. **Python API**
   ```python
   from traceweaver import analyze, load_profile
   result = analyze("file.pcap", profile="open5gs_5gc", model="ollama/qwen3.5:9b")
   ```

3. **MCP Server**（M5）：
   把内核的 built-in tools + 当前 profile tools **全部**暴露为 MCP tools。
   任何 MCP client（Claude Desktop、Cursor、Claude Code、自研 agent）接入后可以：
   - 调 `list_profiles` 看有哪些 profile
   - 调 `load_capture(path, profile)` 加载
   - 调 `query_records`, `get_sbi_calls`, `find_similar_cases` 等做探索
   - 调 `analyze` 拿到完整诊断

4. **HTTP API**（M5）：上面能力的 REST 映射。

---

## 5. Case Memory 设计

**目标**：越用越好用。正确诊断过的 case 下次能被自动引用。

**存储**：`~/.traceweaver/cases/` 用 ChromaDB 本地向量库（M4 引入 `chromadb` 可选依赖）。

**Case 结构**：

```python
class Case(BaseModel):
    case_id: str              # uuid
    created_at: datetime
    profile_name: str
    source_kinds: list[str]   # ["pcap"] 或 ["pcap", "log"]
    symptoms: list[str]       # LLM 在调查过程中观察到的关键现象
    tool_trace: list[ToolInvocation]  # 整个调查轨迹
    final_diagnosis: dict     # schema 校验过的结论
    user_confirmation: Literal["confirmed", "rejected", "pending"]
    expected_match: bool | None  # 如果跑了 expected_diagnosis 对齐，记录是否匹配
    embedding_text: str       # 用于向量化的文本（symptoms + final + context）
```

**写入时机**：
- CLI `traceweaver analyze ... --confirm` → 直接写 `confirmed`
- 否则先写 `pending`，用户可以事后 `traceweaver confirm <case-id>` 或 `reject`
- `confirmed` 进主库，`pending`/`rejected` 进隔离区，不会被 `find_similar_cases` 检索

**检索时机**：
- Agent kernel 在**每轮开始前**主动把 `find_similar_cases` 工具暴露给 LLM
- LLM 自己决定要不要调用
- 返回 top-3 相似 case 的 `symptoms` + `final_diagnosis`（不返回完整 tool_trace，避免 prompt 太长）

**隐私**：case 只存本地，用户可以删；未来支持 export/import 和团队共享是后续扩展。

---

## 6. qwen3.5:9b 基线的配置

基于 v1 实测（`archive/v1/docs-reference/llm/2026-04-16-ollama-qwen3.5-9b-batch-report.md`），9B 在 one-shot 下已经可用，但 tool calling 稳定性需要本项目的验证脚本确认。

**针对 9B 的安全配置**（Agent Kernel 默认值）：

| 参数 | 值 | 理由 |
|------|---|------|
| `max_rounds` | 5 | 9B 超过 5 轮会遗忘早期观察 |
| `tools_per_round` | 2 | 太多并行 tool call 9B 容易选错 |
| `max_tools_visible` | 8 | 超过 8 个 9B 的工具选择质量下降 |
| `tool_result_token_budget` | 4096 | 每次 tool 返回超出则截断 |
| `strict_json_schema` | True | 强制 response_format |
| `schema_retry_count` | 1 | schema 不合自动重试一次 |
| `parallel_tool_calls` | False | 9B 并行 tool call 容易乱 |
| `think_mode` | False | qwen3 系列默认注入 `extra_body={"think": false}`（v1 已验证） |

---

## 7. 模块化交付计划

**每个 milestone 都是端到端可用产品**。没有"半成品状态"。

### M1 — Walking Skeleton（~2 周）

**交付**：LLM-first 的 5GC pcap 诊断 CLI。

**包含**：
- Layer 0：`PcapSource` 一个（tshark 封装）
- Layer 1：Profile 机制（YAML + local directory 扫描）+ 内置 5GC profile（从 v1 资产重组）
- Layer 2：Tool 契约 + built-in tools（`query_records`, `get_records_around`, `search_knowledge`）+ 5GC profile 的 5-7 个工具
- Layer 3：Agent Kernel（原生 tool calling + budget + cache + schema 校验）
- Layer 4：`LLMIntelligence`（litellm，基线 qwen3.5:9b）
- Layer 5：CLI

**不含**：Extension 注册、log source、Case Memory、MCP server、HTTP API、pip 分发。

**验收**：
- `traceweaver analyze tests/fixtures/pcap/01_registration_success.pcapng --profile open5gs_5gc --model ollama/qwen3.5:9b` 能跑出结论
- 28 个 fixture pcap 全部跑通，无崩溃
- 至少 10/16 canonical 样本 verdict 命中（v1 基线是 11/13，允许 LLM-only 方案初期下降，关键是覆盖面）

### M2 — Extensibility（~1 周）

**交付**：第三方能写自己的工具和 profile（本地目录方式）。

**包含**：
- Extension 注册机制（`~/.traceweaver/extensions/tools.yaml`）
- Profile scanning from `$TRACEWEAVER_PROFILES_PATH`
- 开发者文档：`docs/guides/writing-a-profile.md`, `docs/guides/writing-a-tool.md`
- 一个示例 extension（比如 `correlate_5gc_with_open5gs_logs`）

**不含**：pip 分发（留给 M2 后期或独立迭代）。

**验收**：按文档写的新 profile 和新 tool 能被 CLI 识别并调用。

### M3 — Multi-Source（~1.5 周）

**交付**：pcap + 日志联合诊断能力。

**包含**：
- `LogSource`（支持 json line / syslog / 用户自定义 regex）
- `ComposedSource`（时间戳排序 + 关联键合并）
- Built-in tools：`get_logs_around(seq)`, `query_logs(filter)`
- 5GC profile 增加日志关联样例（open5gs AMF/SMF 日志格式）

**验收**：`traceweaver analyze file.pcap --log amf.log --log smf.log` 能跑通，LLM 能引用日志帮助诊断。

### M4 — Case Memory（~1 周）

**交付**：诊断结果能反哺，越用越准。

**包含**：
- ChromaDB 本地案例库
- `traceweaver confirm <case-id>` / `reject <case-id>` CLI
- Built-in tool `find_similar_cases`
- Agent kernel 在 loop 开始前自动暴露该工具

**验收**：
- 先用 M3 能力跑一次诊断并 `--confirm`
- 第二次跑类似 pcap 时，LLM 能主动调用 `find_similar_cases` 并引用历史 case

### M5 — Agent Ecosystem（~1.5 周）

**交付**：TraceWeaver 可被任何 agent 生态接入。

**包含**：
- `traceweaver serve mcp` — MCP server 模式，暴露所有 built-in + profile tools
- `traceweaver serve http` — HTTP REST API
- `MCPAgentIntelligence` — 可把外部 agent 作为推理后端
- 一个演示：Claude Desktop 通过 MCP 直连 TraceWeaver

**验收**：
- MCP client（可用 `mcp-inspector` 或 Claude Desktop）连上 TraceWeaver 能看到工具列表并调用
- 用外部 agent 作为 intelligence 能跑出与 LLM intelligence 相似的结论

### 可选后期

- **pip 分发**：发布 `traceweaver` + `traceweaver-profile-5gc` 到 PyPI
- **更多 source**：OpenTelemetry trace、Netflow、Prometheus metrics
- **更多 profile**：HTTP、DNS、SIP/VoIP、MQTT、RTP/QoE

---

## 8. 红线清单（必须遵守）

1. ❌ 不保留任何 v1 代码兼容层
2. ❌ 不写"规则兜底 + LLM 补充"的混合诊断
3. ❌ 不在工具里做诊断判断（只返回事实）
4. ❌ 不在 core 里写协议/行业特定逻辑
5. ❌ 不让 core 依赖某个具体 profile
6. ❌ 不假设 LLM 有多模型轮值（M1 单后端）
7. ❌ 不做"半成品 M2 → M3 → ..."（每个 M 都完整可用）

---

## 9. 即将执行

**本轮不动代码，只出**：
1. 本文档（你现在看的）
2. `docs/guides/python-packaging-profiles.md`
3. `scripts/validate_tool_calling.py`

**验证脚本通过后的下一轮**：
- 开 M1 新分支
- 新建 `traceweaver/` 空目录
- 按 Layer 0 → 1 → 2 → 3 → 4 → 5 顺序实现 M1
- 跑全量 fixture 回归

**M1 开始前的唯一门槛**：`scripts/validate_tool_calling.py` 在你的环境上证明 qwen3.5:9b 能稳定做 tool calling。
