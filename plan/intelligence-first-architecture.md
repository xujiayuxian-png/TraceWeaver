# TraceWeaver 智能优先架构（修订版）

## 1. 核心理念转变

### 1.1 原方案问题

原方案的链路是：

```
pcap → tshark → records → events → sessions → 状态机 → 规则引擎 → findings → LLM解释
```

这是一个**规则重、智能轻**的架构：

- LLM 被放在链路末端，仅做"解释器"
- 80% 的诊断智能依赖手写规则
- 规则维护成本高，且只能覆盖已知模式
- 对未见过的故障模式无能为力

### 1.2 修订后理念

```
pcap → 结构化数据工程 → LLM 作为主推理引擎
```

**关键转变**：

- **结构化数据工程是不可省略的**（tshark 抽取 → 事件识别 → 会话组装），这不是规则，是数据工程
- **LLM 是诊断引擎**，不是解释器。它接收结构化会话数据，自行推理问题
- **规则降级为"信号标注器"**：不做诊断，只标注明显信号（Reject cause code、超时、错误码）
- **不同能力的模型获得不同程度的支撑**

### 1.3 分层智能策略

| 模型能力 | 输入 | 推理方式 |
|----------|------|----------|
| 顶级模型 (GPT-4/Claude) | 结构化时间线 + 少量信号标注 | 自由推理，可请求额外 tshark 查询 |
| 中等模型 (70B) | 结构化时间线 + 信号标注 + 聚焦 prompt | 引导式推理 |
| 小模型 (8B-14B) | 结构化时间线 + 信号标注 + CoT prompt + RAG 知识 | 模板化推理 + 知识增强 |

**核心原则：所有模型共享同一份高质量结构化数据，差异仅在 prompt 策略和知识注入深度。**

---

## 2. 修订后数据链路

```
pcap/pcapng
    │
    ▼
┌─────────────────────┐
│  Structured Extractor│  ← 确定性代码，不含规则
│  (tshark 抽取 +      │
│   字段标准化)         │
└─────────┬───────────┘
          │ NormalizedRecord[]
          ▼
┌─────────────────────┐
│  Session Assembler   │  ← 确定性代码，跨协议关联
│  (事件识别 +         │
│   会话分组 +          │
│   时间线构建)         │
└─────────┬───────────┘
          │ Session{ timeline, events, metadata }
          ▼
┌─────────────────────┐
│  Signal Annotator    │  ← 轻量标注（替代重规则引擎）
│  (明显异常标注 +      │
│   缺失步骤标记 +      │
│   错误码提取)         │
└─────────┬───────────┘
          │ AnnotatedSession{ signals[] }
          ▼
┌─────────────────────┐
│  LLM Diagnosis Engine│  ← 主推理引擎
│  (Prompt 选择 +      │
│   RAG 知识注入 +      │
│   结构化输出校验)     │
└─────────┬───────────┘
          │ DiagnosisResult{ verdict, causes, evidence, suggestions }
          ▼
┌─────────────────────┐
│  Report Generator    │
└─────────────────────┘
```

---

## 3. 各层详细设计

### 3.1 Structured Extractor（结构化抽取层）

**职责**：从 pcap 中抽取干净的结构化记录。纯数据工程，无规则逻辑。

**实现方式**：调用 tshark，按协议配置抽取字段，输出标准化记录。

**输出数据结构**：

```python
class NormalizedRecord(BaseModel):
    frame_number: int
    timestamp_epoch: float    # frame.time_epoch
    timestamp_relative: float # 相对时间
    primary_protocol: str     # 主协议: ngap, nas_5gs, http2, pfcp
    protocol_layers: list[str] = Field(default_factory=list)  # 由 frame.protocols 拆分
    src_ip: str
    dst_ip: str
    connection_key: str = "" # 例如 tcp.stream，用于 HTTP2/PFCP 等连接内关联
    fields: dict[str, Any] = Field(default_factory=dict)    # 协议相关字段
    raw_info: str             # tshark info 列
```

**设计要点**：

- 单次 tshark 调用抽取所有目标协议的关键字段（一次遍历）
- 字段清单按 profile 配置，但抽取逻辑是通用代码
- 不做任何语义判断，只做字段抽取和类型标准化
- 抽取层必须保留 `frame.time_epoch`、`frame.protocols`、`frame.info`，避免上层数据契约与 tshark 输出脱节
- 不要过早把多层协议压扁为单个 `protocol`，否则会丢失 `NGAP` 承载 `NAS-5GS` 这类关键上下文
- 连接内标识（如 `tcp.stream`）要作为一等字段保留，后续 `HTTP2` 配对不能仅依赖 `http2.streamid`

### 3.2 Session Assembler（会话组装层）

**职责**：将离散记录关联为可分析的会话对象。确定性代码，不含诊断逻辑。

详细方案见 `cross-protocol-correlation.md`。

**输出数据结构**：

```python
class Event(BaseModel):
    event_type: str           # REGISTRATION_REQUEST, AUTH_FAILURE, ...
    frame_number: int
    timestamp: float
    protocol: str
    key_fields: dict[str, Any] = Field(default_factory=dict)  # 该事件的关键字段子集

class SessionTimeline(BaseModel):
    events: list[Event] = Field(default_factory=list)
    duration_ms: float = 0.0
    last_state: str = ""      # 流程跟踪器的当前状态

class UESession(BaseModel):
    session_id: str
    ran_ue_ngap_id: Optional[str] = None
    amf_ue_ngap_id: Optional[str] = None
    suci: Optional[str] = None
    supi: Optional[str] = None
    registration_timeline: SessionTimeline = Field(default_factory=SessionTimeline)
    pdu_sessions: list[PDUSessionFlow] = Field(default_factory=list)
    sbi_calls: list[SBICall] = Field(default_factory=list)

class PDUSessionFlow(BaseModel):
    pdu_session_id: str
    timeline: SessionTimeline = Field(default_factory=SessionTimeline)
    pfcp_flows: list[PFCPFlow] = Field(default_factory=list)
    sbi_calls: list[SBICall] = Field(default_factory=list)

class SBICall(BaseModel):
    connection_key: str = ""   # 连接作用域键，如 tcp.stream
    stream_id: int
    method: str = ""
    path: str = ""
    status: Optional[int] = None
    request_frame: int = 0
    response_frame: Optional[int] = None
    service: str = ""        # nausf-auth, nudm-uecm, nsmf-pdusession, ...
    src_ip: str = ""          # 请求方 IP（用于 NF 角色推断）
    dst_ip: str = ""          # 目标方 IP（用于 SMF/AUSF 等 IP 推断）
    timestamp: float = 0.0
```

**事件识别**：基于协议字段的确定性映射，不是规则判断。例如：

```python
# 这不是规则，是协议语义映射
EVENT_MAP = {
    ("nas_5gs", 65): "REGISTRATION_REQUEST",
    ("nas_5gs", 66): "REGISTRATION_ACCEPT",
    ("nas_5gs", 67): "REGISTRATION_COMPLETE",
    ("nas_5gs", 68): "REGISTRATION_REJECT",
    ("nas_5gs", 86): "AUTHENTICATION_REQUEST",
    ("nas_5gs", 87): "AUTHENTICATION_RESPONSE",
    ("nas_5gs", 88): "AUTHENTICATION_RESULT",
    ("nas_5gs", 89): "AUTHENTICATION_FAILURE",
    ("nas_5gs", 93): "SECURITY_MODE_COMMAND",
    ("nas_5gs", 94): "SECURITY_MODE_COMPLETE",
    ("nas_5gs", 95): "SECURITY_MODE_REJECT",
    ("nas_5gs", 193): "PDU_SESSION_ESTABLISHMENT_REQUEST",
    ("nas_5gs", 194): "PDU_SESSION_ESTABLISHMENT_ACCEPT",
    ("nas_5gs", 195): "PDU_SESSION_ESTABLISHMENT_REJECT",
    ("nas_5gs", 69): "DEREGISTRATION_REQUEST_UE_ORIG",
    ("nas_5gs", 70): "DEREGISTRATION_ACCEPT_UE_ORIG",
    ("nas_5gs", 71): "DEREGISTRATION_REQUEST_NW",
    ("nas_5gs", 72): "DEREGISTRATION_ACCEPT_NW",
    ("nas_5gs", 76): "SERVICE_REJECT",
    # ...
}
```

**流程跟踪器**（替代重量级状态机）：

不再是一个试图做诊断的状态机，而是一个轻量的**流程进度跟踪器**：

```python
# 仅跟踪流程走到哪一步，不做诊断判断
REGISTRATION_FLOW = [
    "INITIAL_UE_MESSAGE",
    "REGISTRATION_REQUEST",
    "AUTHENTICATION_REQUEST",
    "AUTHENTICATION_RESPONSE",
    "SECURITY_MODE_COMMAND",
    "SECURITY_MODE_COMPLETE",
    "REGISTRATION_ACCEPT",
]

# 跟踪器输出：
# - current_step: 当前走到哪一步
# - completed_steps: 已完成的步骤列表
# - missing_steps: 预期但未出现的步骤
# - stuck_at: 如果超时，停在哪一步
# - anomalies: 异常跳转（如跳过某步骤、收到 Reject）
```

### 3.3 Signal Annotator（信号标注层）

**职责**：对会话数据做轻量标注，为 LLM 提供"注意力提示"。

**关键区别：Signal Annotator 不做诊断，只标注客观信号。**

```python
class Signal(BaseModel):
    signal_type: str          # REJECT_RECEIVED, TIMEOUT, ERROR_CODE, MISSING_STEP, ...
    severity: str             # info, warning, error
    frame_number: Optional[int] = None
    description: str          # 对客观事实的简短描述
    raw_value: Optional[str] = None  # 原始值（如 cause code）

# 信号标注器示例（每个标注器 5-10 行代码）：

def annotate_reject_causes(session: UESession) -> list[Signal]:
    """标注所有包含 reject/failure cause code 的事件"""
    signals = []
    for event in session.registration_timeline.events:
        cause = event.key_fields.get("5gmm_cause")
        if cause:
            signals.append(Signal(
                signal_type="REJECT_CAUSE",
                severity="error",
                frame_number=event.frame_number,
                description=f"{event.event_type} with cause: {cause}",
                raw_value=cause,
            ))
    return signals

def annotate_missing_steps(session: UESession) -> list[Signal]:
    """标注预期流程中缺失的步骤"""
    # ...

def annotate_timeouts(session: UESession, threshold_ms: float = 5000) -> list[Signal]:
    """标注步骤间超时"""
    # ...

def annotate_sbi_errors(session: UESession) -> list[Signal]:
    """标注 SBI 调用失败（HTTP 4xx/5xx）"""
    # ...

def annotate_pfcp_failures(session: UESession) -> list[Signal]:
    """标注 PFCP 失败"""
    # ...

def annotate_retries(session: UESession) -> list[Signal]:
    """标注重试行为"""
    # ...
```

**与重规则引擎的区别**：

| 重规则引擎 | 信号标注器 |
|-----------|-----------|
| 输出诊断结论 | 输出客观事实标注 |
| 需要写 50+ 条规则 | 只需 10-15 个标注器 |
| 规则之间可能冲突 | 标注互不干扰 |
| 需要置信度/优先级系统 | 不需要 |
| 维护成本高 | 维护成本低 |
| 对未知模式无效 | 仍标注可观察信号 |

### 3.4 LLM Diagnosis Engine（LLM 诊断引擎）

**职责**：接收结构化会话数据 + 信号标注，输出诊断结论。这是系统的**主推理引擎**。

**Prompt 构建策略**：

```python
def build_diagnosis_prompt(
    session: AnnotatedSession,
    model_tier: str,        # "large", "medium", "small"
    rag_context: Optional[str],
) -> str:
    # 1. 系统角色
    system = "你是 5GC 网络故障诊断专家..."

    # 2. 结构化会话数据（所有模型都收到）
    timeline_text = format_timeline(session)

    # 3. 信号标注（所有模型都收到）
    signals_text = format_signals(session.signals)

    # 4. 根据模型能力选择 prompt 策略
    if model_tier == "large":
        # 大模型：直接给数据，让它自由推理
        instruction = "请分析以上会话时间线，给出诊断结论。"
    elif model_tier == "medium":
        # 中等模型：给一些引导
        instruction = """请按以下步骤分析：
        1. 流程走到了哪一步？
        2. 哪里出了问题？
        3. 根据信号标注和时间线，推断根因
        4. 给出排查建议"""
    else:
        # 小模型：给 CoT 模板 + RAG 知识
        instruction = build_cot_template(session)

    # 5. RAG 知识注入（小模型必须，大模型可选）
    knowledge = ""
    if rag_context and model_tier in ("small", "medium"):
        knowledge = f"\n\n## 参考知识\n{rag_context}"

    # 6. 输出格式约束
    output_schema = DIAGNOSIS_OUTPUT_SCHEMA

    return assemble_prompt(system, timeline_text, signals_text,
                          knowledge, instruction, output_schema)
```

**输出结构**：

```python
class Evidence(BaseModel):
    frame_number: int
    description: str
    field_values: dict[str, str] = Field(default_factory=dict)

class DiagnosisResult(BaseModel):
    verdict: str              # OK, FAIL, INCONCLUSIVE
    failure_point: str = ""   # 流程卡在哪一步
    root_cause: str = ""      # 推断的根因
    confidence: str = "medium" # high, medium, low
    evidence: list[Evidence] = Field(default_factory=list)  # 支持结论的证据
    suggestions: list[str] = Field(default_factory=list)    # 排查建议
    limitations: list[str] = Field(default_factory=list)    # 抓包缺口、关联歧义、版本兼容限制
    reasoning: str = ""       # 推理过程（可选，用于 debug）
```

**诊断约束**：

- 当关键链路依赖 `low_confidence` 或 `unresolved` 关联时，`LLM` 必须在 `limitations` 中明确说明，而不是给出伪确定性结论
- 诊断引擎应始终能降级为“结构化时间线 + signals + flow tracker + limitations”的非结论输出，避免模型失效时产品整体失效

### 3.5 RAG 知识层

**职责**：为 LLM（尤其是小模型）提供领域知识增强。

**知识类型**：

- **3GPP Cause Code 说明**：每个 5GMM/5GSM cause code 的含义和常见触发场景
- **Open5GS 模块职责**：AMF/SMF/UPF/AUSF/UDM/PCF 各自职责和交互关系
- **常见故障模式**：典型故障的症状、时间线特征、排查方向
- **SBI 接口说明**：各 SBI 服务的用途和典型错误

**检索策略**：

根据信号标注生成检索 query。例如：

- 收到 `REGISTRATION_REJECT with cause 72` → 检索 "5GMM cause 72"
- SBI `/nausf-auth` 返回 403 → 检索 "AUSF authentication 403"

---

## 4. 与原方案的对比

| 维度 | 原方案 | 修订方案 |
|------|--------|---------|
| 诊断引擎 | 规则引擎 | LLM |
| LLM 角色 | 解释器 | 主推理引擎 |
| 规则数量 | 50+ 条诊断规则 | 10-15 个信号标注器 |
| 状态机 | 重量级诊断状态机 | 轻量流程跟踪器 |
| 新故障覆盖 | 需要写新规则 | LLM 自行推理 |
| 人力投入 | 高（规则+状态机+维护） | 低（数据工程+prompt） |
| 小模型支持 | 规则兜底 | 信号标注+CoT+RAG 兜底 |
| 可解释性 | 规则 ID + 证据帧 | LLM 推理过程 + 证据帧 |
| 结构化保证 | 规则输出天然结构化 | 需要 schema 校验 |

---

## 5. 对 Agent 化的天然支持

修订方案天然适配二期 Agent 化：

- `Structured Extractor` + `Session Assembler` 可以作为 MCP 工具暴露
- `Signal Annotator` 的输出可以作为 Agent 的 observation
- LLM 诊断引擎本身就是 Agent 的推理内核
- 大模型 Agent 可以请求"追加 tshark 查询"（多轮分析）

---

## 6. 前三阶段不做、后续再做的能力

- Plugin/Profile 装配框架 → 阶段 5
- MCP/Agent adapter → 阶段 5 或二期
- 多 profile 支持 → 二期
- 通用 DSL → 不做
- 复杂 Agent 编排 → 二期

---

## 7. 阶段划分（修订版）

### 阶段 1：结构化抽取 + 会话组装

- Structured Extractor
- Session Assembler（含跨协议关联）
- 流程跟踪器
- CLI 输出会话时间线

验收：能从 pcap 输出 UE 注册和 PDU Session 的结构化时间线

### 阶段 2：信号标注 + LLM 诊断

- Signal Annotator（10-15 个标注器）
- LLM Provider 抽象（本地/Ollama/API）
- Prompt 模板（大/中/小模型三套）
- 结构化输出校验

验收：能对典型失败抓包输出 LLM 诊断报告

### 阶段 3：RAG 知识增强 + 报告输出

- RAG 数据源（cause code、模块职责、故障模式）
- 报告生成（JSON + Markdown）
- 小模型诊断质量优化

验收：小模型也能输出可用的诊断报告

### 阶段 4：Profile 化与平台收口

- Profile 机制
- Plugin 注册
- 对外统一接口

---

## 8. 技术栈

- **语言**：Python 3.11+
- **数据模型**：Pydantic v2（数据合约 + schema 校验）
- **tshark 调用**：subprocess，参考 pcap-mcp 的 proc 封装
- **LLM 集成**：litellm（统一接口，支持 Ollama/OpenAI/本地）
- **RAG**：ChromaDB（轻量向量库）+ sentence-transformers
- **CLI**：click 或 typer
- **测试**：pytest
- **包管理**：uv（或 pip + pyproject.toml）
