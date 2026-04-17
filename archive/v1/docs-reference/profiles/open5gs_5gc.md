# Open5GS 5GC Profile

## 简介

Open5GS 5GC Profile 是 TraceWeaver 的核心分析配置，专门用于诊断基于 [Open5GS](https://open5gs.org/) 的 5G Core (5GC) 网络抓包。

### 能力范围

| 功能 | 说明 |
|------|------|
| **UE 注册诊断** | 检测 Registration Reject、Authentication Failure、Security Mode 失败等 |
| **PDU 会话建立** | 诊断会话建立失败、PFCP 关联异常、SBI 调用失败 |
| **多 UE 并发** | 支持同一抓包中多个 UE 的独立诊断 |
| **可见性评估** | 检测捕获是否完整（NGAP/SBI/PFCP 平面可见性） |
| **LLM 辅助诊断** | 规则引擎无法确定时，可调用 LLM 进行推理 |
| **交互式调查** | 提供 Investigation 工具集，支持深度排查 |

### 典型应用场景

```
01_registration_success.pcapng          → OK
03_registration_reject.pcapng           → FAIL (REGISTRATION)
04_authentication_failure.pcapng        → FAIL (AUTHENTICATION)
07_pfcp_failure.pcapng                  → FAIL (PDU_SESSION_ESTABLISHMENT)
08_sbi_failure.pcapng                   → FAIL (SBI)
09_multi_ue_concurrent.pcapng           → OK (2+ scopes)
```

---

## 快速开始

### CLI 使用

```bash
# 基础分析
python -m traceweaver analyze 01_registration_success.pcapng

# 限制分析范围（只分析前 N 个 UE 会话）
python -m traceweaver analyze capture.pcapng --limit 5

# 使用 LLM 增强诊断
python -m traceweaver analyze capture.pcapng --model ollama/qwen3.5:9b

# 交互式调查
python -m traceweaver investigate capture.pcapng --model ollama/qwen3.5:9b

# 只查看抓包中的 scope 列表
python -m traceweaver scopes list capture.pcapng
```

### Python API

```python
from traceweaver import analyze_capture
from pathlib import Path

# 基础分析
result = analyze_capture(
    "01_registration_success.pcapng",
    profile="open5gs_5gc"
)

print(f"Verdict: {result.overall_verdict}")
print(f"Scopes: {result.scope_count}")
for d in result.diagnoses:
    print(f"  - {d.scope_id}: {d.verdict} ({d.confidence})")
```

---

## 架构详解

### 目录结构

```
traceweaver/profiles/open5gs_5gc/
├── profile.py          # 主入口：实现 AnalysisProfile lifecycle
├── runtime.py          # Open5GSAnalysisRuntime: profile 私有运行态
├── investigation.py    # Investigation 工具注册表
├── defaults.py         # 常量：过滤器、解码规则
├── fields.py           # 字段规格：tshark 抽取字段定义
├── domain/             # 领域模型（纯数据结构）
│   ├── records.py      # ExtractedRecordSet, NormalizedRecord
│   ├── events.py       # DetectedEvent, DetectedEventSet
│   ├── sbi.py          # SBICall, SBICallSet
│   ├── pdu.py          # PFCPFlow, PDUSessionFlow, PDUSessionSet
│   ├── sessions.py     # UESession, UESessionSet
│   └── diagnosis.py    # DiagnosticSignal, SessionDiagnosis, DiagnosisReport
├── extract/            # 数据抽取
│   └── records.py      # 5GC 专用 tshark 抽取实现
├── assemble/           # 会话组装
│   ├── ue.py           # UE 会话分组
│   ├── sbi.py          # SBI 调用关联
│   └── pdu.py          # PDU 会话组装
├── diagnosis/          # 诊断引擎
│   ├── engine.py       # 规则诊断
│   ├── llm_engine.py   # LLM 诊断
│   └── signals.py      # 信号收集器
└── events/             # 事件识别
    └── identify.py     # NAS/NGAP 事件检测
```

### 与 Core 的边界

| 层级 | 职责 | 5GC 专属内容 |
|------|------|-------------|
| `core/` | 平台层：编排、契约、通用 tshark | ❌ 无 5GC 概念 |
| `profiles/open5gs_5gc/` | 领域层：5GC 协议解析、诊断逻辑 | ✅ 全部 5GC 逻辑 |

**核心原则**：`core` 不感知 5GC，`profile` 不感知编排。

---

## 分析流程（Lifecycle）

当调用 `analyze_capture()` 时，core 会按顺序调用 profile 的 lifecycle hooks：

```
┌─────────────────────────────────────────────────────────┐
│  Core Analysis Engine (orchestrator)                    │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│  1. extract(path, options)                              │
│     → Open5GSAnalysisRuntime                            │
│     使用 tshark 抽取原始记录，构建 profile 私有运行态       │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│  2. build_scopes(runtime, options)                      │
│     → list[AnalysisScope]                               │
│     组装 UE 会话，关联 SBI/PFCP，生成平台通用 Scope        │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│  3. For each scope:                                      │
│     annotate_signals(scope, runtime) → DiagnosticSignal[] │
│     assess_visibility(scope, signals) → VisibilityAssessment│
│     collect_evidence(scope, signals, visibility) → Evidence[]│
│     diagnose_scope(...) → ScopeDiagnosis                 │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│  4. Core 聚合所有 ScopeDiagnosis 为 AnalysisResult       │
└─────────────────────────────────────────────────────────┘
```

### 各阶段详解

#### 1. Extract - 数据抽取

```python
runtime = profile.extract("capture.pcapng", options=options)
# runtime.record_set: ExtractedRecordSet (原始包记录)
# runtime.warnings: 抽取过程中的警告
```

使用 `core.tshark` 通用能力 + profile 本地字段定义完成抽取。

#### 2. Build Scopes - 会话组装

```python
scopes = profile.build_scopes(runtime, options=options)
```

组装流程：
1. `group_ue_sessions()` - 按 UE 标识分组
2. `pair_sbi_calls()` - 识别 SBI HTTP/2 调用
3. `correlate_sbi_to_sessions()` - 关联 SBI 到 UE
4. `build_pdu_sessions_for_ue()` - 组装 PDU 会话
5. `correlate_pfcp_to_pdu()` - 关联 PFCP 流量

#### 3. Diagnose Scope - 单 Scope 诊断

```python
signals = profile.annotate_signals(scope, runtime)      # 提取信号
visibility = profile.assess_visibility(scope, signals)  # 评估可见性
evidence = profile.collect_evidence(...)                # 收集证据
diagnosis = profile.diagnose_scope(...)                   # 产出诊断
```

---

## 领域模型

### 核心实体关系

```
ExtractedRecordSet
    └── records: list[NormalizedRecord]  (原始包)
        
UESession (UE 会话)
    ├── ran_ue_ngap_id / amf_ue_ngap_id
    ├── suci / supi
    ├── records: list[NormalizedRecord]  (归属该 UE 的包)
    ├── events: list[DetectedEvent]      (NAS/NGAP 事件)
    ├── sbi_calls: list[SBICall]         (关联的 SBI 调用)
    └── pdu_sessions: list[PDUSessionFlow]
        └── pfcp_flows: list[PFCPFlow]   (PFCP 会话)
```

### 诊断信号（DiagnosticSignal）

| 信号类别 | 示例信号 | 含义 |
|---------|---------|------|
| **NAS Mobility** | `REGISTRATION_REQUEST`, `REGISTRATION_ACCEPT`, `REGISTRATION_REJECT` | UE 注册流程 |
| | `AUTHENTICATION_REQUEST`, `AUTHENTICATION_FAILURE` | 鉴权流程 |
| | `SECURITY_MODE_COMPLETE`, `SECURITY_MODE_REJECT` | 安全模式 |
| **Session Mgmt** | `PDU_SESSION_ESTABLISHMENT_REQUEST`, `PDU_SESSION_ESTABLISHMENT_ACCEPT` | PDU 会话建立 |
| | `T3580_EXPIRY` | 定时器超时（重试信号） |
| **SBI** | `SBI_NNF_REGISTER`, `SBI_NNF_REGISTER_RESPONSE` | NF 注册 |
| | `SBI_NAMF_COMM_UE_CONTEXT_TRANSFER` | AMF 间切换 |
| **PFCP** | `PFCP_SESSION_ESTABLISHMENT_REQUEST`, `PFCP_SESSION_ESTABLISHMENT_RESPONSE` | PFCP 会话 |
| **Visibility** | `NGAP_VISIBLE`, `SBI_HTTP2_VISIBLE`, `PFCP_VISIBLE` | 各平面可见性 |
| | `PARTIAL_CAPTURE_NO_PFCP`, `LOW_RECORD_COUNT` | 捕获质量警告 |

### 诊断结论（ScopeDiagnosis.verdict）

| Verdict | 含义 | 典型场景 |
|---------|------|---------|
| `OK` | 流程成功完成 | Registration Success + PDU Established |
| `FAIL` | 明确的失败 | Registration Reject, Auth Failure |
| `FAIL_THEN_OK` | 失败后恢复 | 重试成功（如 T3580 触发后恢复） |
| `INCONCLUSIVE` | 无法确定 | 捕获不完整、关键包缺失 |

### 可见性评估（VisibilityAssessment）

当捕获不完整时，visibility 会影响最终 verdict：

```python
completeness: "complete" | "limited" | "partial"
missing_segments: ["ngap", "pfcp"]  # 缺失的协议平面
weak_links: ["capture_tail"]        # 薄弱环节
warnings: ["capture ends at scope tail"]  # 具体警告
```

**可见性约束示例**：
- 如果 `completeness == "partial"` 且 verdict 是 `OK` → 降级为 `INCONCLUSIVE`
- 如果 `capture_tail` 警告 + 无明确成功信号 → 降级为 `INCONCLUSIVE`

---

## 诊断引擎

### 规则引擎（默认）

基于信号状态机的确定性诊断：

```python
# 伪代码逻辑
if REGISTRATION_REJECT in signals:
    return FAIL(failure_point="REGISTRATION")
if AUTHENTICATION_FAILURE in signals:
    return FAIL(failure_point="AUTHENTICATION")
if PDU_SESSION_ESTABLISHMENT_REJECT in signals:
    return FAIL(failure_point="PDU_SESSION_ESTABLISHMENT")
if REGISTRATION_ACCEPT in signals and PDU_SESSION_ESTABLISHMENT_ACCEPT in signals:
    return OK()
# ... 更多规则
```

### LLM 引擎（可选）

当提供 `llm_provider` 时，复杂场景会调用 LLM：

```python
result = analyze_capture(
    "ambiguous.pcapng",
    llm_provider=your_llm_provider
)
```

LLM 诊断触发条件：
- 规则引擎无法确定 verdict
- 存在矛盾信号需要推理
- 用户明确请求 investigation

---

## Investigation 工具集

当使用 `investigate_capture()` 时，profile 提供以下工具：

| 工具 | 功能 |
|------|------|
| `get_scope_info` | 获取 Scope 基本信息 |
| `get_signals` | 列出该 Scope 的所有诊断信号 |
| `get_evidence` | 查看证据项（时间线、SBI 调用等）|
| `get_visibility` | 查看可见性评估详情 |
| `query_records` | 查询原始包记录（按 frame/协议过滤）|
| `query_events` | 查询 NAS/NGAP 事件 |
| `query_sbi_calls` | 查询 SBI 调用详情 |

Investigation 支持多轮迭代，LLM 可决定下一步查询什么。

---

## 配置与选项

### AnalysisOptions 字段

```python
from traceweaver import AnalysisOptions

options = AnalysisOptions(
    display_filter="ngap || http2 || pfcp",  # 自定义显示过滤器
    decode_as=["tcp.port==7777,http2"],       # 自定义解码规则
    scope_limit=5,                            # 只分析前 5 个 UE
    record_limit=10000,                       # 限制原始记录数（调试用）
)
```

### Profile 本地常量

```python
# traceweaver/profiles/open5gs_5gc/defaults.py
DEFAULT_5GC_DISPLAY_FILTER = "ngap || http2 || pfcp"
HTTP2_DECODE_AS_RULES = ["tcp.port==7777,http2"]
PRIMARY_PROTOCOL_ORDER = ["NGAP", "HTTP2", "PFCP"]

# traceweaver/profiles/open5gs_5gc/fields.py
FIELD_SPECS = {...}  # 80+ 字段定义
SINGLE_VALUE_FIELDS = {...}  # 单值字段集合
```

---

## 扩展指南

### 添加新信号类型

1. 在 `diagnosis/signals.py` 添加收集逻辑：

```python
def collect_signals(session: UESession, records: ExtractedRecordSet) -> list[DiagnosticSignal]:
    signals = []
    # ... 现有信号
    
    # 新增：检测新的失败模式
    if _detect_new_failure_pattern(session):
        signals.append(DiagnosticSignal(
            name="NEW_FAILURE_PATTERN",
            source="custom",
            # ...
        ))
    return signals
```

2. 在 `diagnosis/engine.py` 添加诊断规则：

```python
if any(s.name == "NEW_FAILURE_PATTERN" for s in signals):
    return SessionDiagnosis(
        verdict="FAIL",
        failure_point="NEW_POINT",
        # ...
    )
```

### 支持新协议平面

1. 在 `fields.py` 添加新字段规格
2. 在 `extract/records.py` 添加抽取逻辑
3. 在 `assemble/` 添加组装逻辑（如果需要）
4. 在 `diagnosis/signals.py` 添加新信号

### 自定义 Investigation 工具

在 `investigation.py` 添加：

```python
def build_investigation_tool_registry(context: DiagnosisContext, diagnosis):
    registry = InvestigationToolRegistry(tools=[
        # ... 现有工具
        Tool(
            name="my_custom_tool",
            description="描述工具功能",
            parameters={...},
            handler=_handle_my_custom_tool,
        ),
    ])
    return registry
```

---

## 故障排查

### 常见问题

**Q: 分析结果为空（no scopes）**
- 检查抓包是否包含 NGAP/HTTP2/PFCP 流量
- 尝试自定义 `display_filter` 扩大范围
- 检查 `record_set.warnings` 是否有抽取错误

**Q: 所有诊断都是 INCONCLUSIVE**
- 检查 `visibility.warnings`，可能是捕获不完整
- 确认抓包包含完整的注册流程（从 Initial UE Message 开始）

**Q: SBI 调用未被识别**
- 确认 HTTP/2 流量在 7777 端口（或自定义 decode_as）
- 检查 `fields.py` 中的 HTTP2 字段规格是否匹配 tshark 版本

**Q: PFCP 关联失败**
- 确认 PFCP 流量在同一抓包中
- 检查时间窗口：PFCP 和 NGAP 事件时间差是否在合理范围

### 调试技巧

```python
# 查看原始抽取结果
runtime = profile.extract("capture.pcapng", options=options)
print(f"Records: {len(runtime.record_set.records)}")
print(f"Warnings: {runtime.warnings}")

# 查看组装后的 sessions
scopes = profile.build_scopes(runtime, options=options)
for scope in scopes:
    print(f"Scope: {scope.scope_id}, records: {len(scope.records)}")
    
# 查看信号详情
signals = profile.annotate_signals(scope, runtime, options=options)
for s in signals:
    print(f"  Signal: {s.name} ({s.category})")
```

---

## 参考

- [TraceWeaver Core 架构](../architecture/core.md)
- [Adding a New Profile](../guides/adding-profile.md)
- [Investigation Tools](../guides/investigation.md)
- [Open5GS 官方文档](https://open5gs.org/open5gs/docs/)
