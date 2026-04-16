我直接给你一版可落地的“一步到位终态重构方案”，目标不是讨论愿景，而是明确 **该怎么改目录、怎么定 contract、怎么迁移现有代码、怎么保证后续 agent 不再绑死 5GC/Open5GS**。# TraceWeaver 一步到位终态重构方案

## 1. 方案结论

我建议你现在直接做一次 **一步到位的终态重构**：

- **[目标形态]** `平台 core + 首个官方 profile(open5gs_5gc)`
- **[不是目标]** 在当前 5GC/Open5GS 绑定结构上继续堆 agent
- **[核心动作]** 直接把现有 5GC 语义从 [traceweaver](cci:9://file:///home/ailink/code/TraceWeaver/traceweaver:0:0-0:0) 主干中剥离，重组为 `core + profiles/open5gs_5gc`
- **[执行原则]** 不做兼容层、不保留旧入口、不保留旧命名、不维护双轨结构
- **[交付原则]** 只接受终态目录、终态 contract、终态 CLI、终态导入路径

一句话：

> **直接把系统重写到终态架构上，然后只在终态架构上继续做完整 agent。**

不然你后面做的 tool schema、agent state、prompt contracts、report schema 都会继续被 5GC 绑死。

---

# 2. 这次重构要解决的根问题

## 当前问题

现在仓库里实际上存在三类混杂：

- **[平台层]** tshark 调用、LLM provider、CLI、报告
- **[5GC 域层]** UE Session、PDU Session、NGAP/NAS/PFCP/SBI
- **[Open5GS 经验层]** `tcp.port==7777,http2`、SBI path 习惯、特定 heuristics

这三层现在没有被清楚隔开。

## 正确分层

应该拆成：

- **[Core]** 平台无关的分析引擎、Agent、Evidence、Tooling、统一接口
- **[Domain Profile]** 某个场景的结构化抽取、事件识别、关联组装、信号标注、Prompt、知识
- **[Vendor Flavor]** 某个厂商/实现的特定 heuristics 和默认配置

对于你当前项目，第一版可以先做到：

- **[Profile]** `open5gs_5gc`

先不额外拆 `3gpp_5gc` 与 `open5gs` 两层，避免抽象过重。  
但代码组织必须预留这条路。

---

# 3. 重构目标

## 必须达成

- **[统一入口通用化]** 所有主流程以 `profile` 驱动
- **[Core 去 5GC 化]** core 中不再直接出现 `UE/PDU/AMF/SMF/Open5GS`
- **[现有 5GC 能力保留]** 不丢当前已实现的 records/events/sessions/sbi/pdu/pfcp/diagnosis
- **[旧接口直接废弃]** 旧 CLI/API/模块路径不再保留，也不做内部转发
- **[Agent 对 core contract 编程]** 后续 agent 不依赖 [UESession](cci:2://file:///home/ailink/code/TraceWeaver/traceweaver/models/sessions.py:8:0-26:68)、[PDUSessionFlow](cci:2://file:///home/ailink/code/TraceWeaver/traceweaver/models/pdu.py:20:0-33:60)
- **[一次性切换]** 所有 import、测试、CLI、文档一次性切到新结构，不允许新旧并存

## 明确不做

- **[不做万能 DSL]** 不把关联算法都配置化
- **[不做多 profile 同时铺开]** 先只把 `open5gs_5gc` 收编进新架构
- **[不先做重 UI]**
- **[不先做复杂 plugin marketplace]**
- **[不做 compat / adapter / wrapper]** 任何“先包一层以后再删”的做法都不采用

---

# 4. 最终目录结构

我建议直接落成下面这个结构。

```text
traceweaver/
  core/
    analysis/
      engine.py
      result.py
      options.py
    contracts/
      record.py
      event.py
      scope.py
      signal.py
      evidence.py
      diagnosis.py
      investigation.py
      visibility.py
    profile/
      base.py
      registry.py
      loader.py
    tools/
      registry.py
      executor.py
      schemas.py
    agent/
      planner.py
      runner.py
      termination.py
      evidence_store.py
    llm/
      provider.py
      prompt_runtime.py
      output_validator.py
    rag/
      retriever.py
    report/
      renderer.py
    tshark/
      runner.py
      fields.py
      packet_access.py

  profiles/
    open5gs_5gc/
      profile.py
      fields.py
      extract/
        records.py
      events/
        identify.py
      assemble/
        ue.py
        sbi.py
        pdu.py
      signals/
        annotators.py
      diagnosis/
        prompt.py
        formatter.py
      knowledge/
      report/
        markdown.py
      tools/
        session_tools.py
        frame_tools.py

  cli.py
```

---

# 5. Core contract 设计

这里是最关键的。  
后续所有 `agent / tool / llm / report` 都应该只依赖这些 contract。

## 5.1 `CaptureRecord`

平台级最小记录对象。

```python
class CaptureRecord(BaseModel):
    frame_number: int
    time_epoch: float
    time_relative: float | None = None
    primary_protocol: str
    protocol_layers: list[str] = Field(default_factory=list)
    src_ip: str = ""
    dst_ip: str = ""
    src_port: int | None = None
    dst_port: int | None = None
    connection_key: str = ""
    raw_info: str = ""
    fields: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
```

- **[作用]** 统一替代当前平台层对 `NormalizedRecord` 的依赖
- **[说明]** 这个就是终态记录对象，`NormalizedRecord` 不再作为外部主 contract 存在

---

## 5.2 `StructuredEvent`

平台级事件对象。

```python
class StructuredEvent(BaseModel):
    event_id: str
    scope_hint: str = ""
    event_type: str
    protocol: str
    time_epoch: float
    frame_number: int
    severity: str = "info"
    key_fields: dict[str, Any] = Field(default_factory=dict)
    attributes: dict[str, Any] = Field(default_factory=dict)
```

- **[作用]** 替代“事件一定是 5GC NAS/NGAP 事件”的假设
- **[说明]** `event_type` 可由 profile 自定义，比如：
  - 5GC: `REGISTRATION_REQUEST`
  - Web: `HTTP_REQUEST`
  - RTP: `STREAM_GAP`

---

## 5.3 `AnalysisScope`

这是平台真正的核心对象。  
以后不能让 agent 直接以 [UESession](cci:2://file:///home/ailink/code/TraceWeaver/traceweaver/models/sessions.py:8:0-26:68) 为公共 contract。

```python
class AnalysisScope(BaseModel):
    scope_id: str
    scope_type: str
    display_name: str = ""
    start_time_epoch: float | None = None
    end_time_epoch: float | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    records: list[CaptureRecord] = Field(default_factory=list)
    events: list[StructuredEvent] = Field(default_factory=list)
    children: list["AnalysisScope"] = Field(default_factory=list)
    related_entities: dict[str, list[str]] = Field(default_factory=dict)
```

### 例子

- **[5GC]**
  - `scope_type="ue_session"`
  - child: `scope_type="pdu_session"`

- **[Web]**
  - `scope_type="request_flow"`
  - child: `scope_type="backend_call_group"`

- **[音视频]**
  - `scope_type="media_stream"`

这一步一旦立住，平台就脱离 5GC 了。

---

## 5.4 `DiagnosticSignal`

保留你现在“信号标注器”的思路，但做成平台契约。

```python
class DiagnosticSignal(BaseModel):
    signal_id: str
    name: str
    scope_id: str
    category: str = ""
    confidence: str = "high"
    summary: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
```

---

## 5.5 `EvidenceItem`

后续 agent 的证据存储必须统一。

```python
class EvidenceItem(BaseModel):
    evidence_id: str
    scope_id: str = ""
    source_type: str
    source_name: str
    summary: str
    frame_numbers: list[int] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)
    supports: list[str] = Field(default_factory=list)
    contradicts: list[str] = Field(default_factory=list)
```

---

## 5.6 `VisibilityAssessment`

这是你后面做 `INCONCLUSIVE` 的关键，不要再把它只当 warning。

```python
class VisibilityAssessment(BaseModel):
    scope_id: str
    completeness: str
    missing_segments: list[str] = Field(default_factory=list)
    weak_links: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
```

- **[意义]** `INCONCLUSIVE` 不只是 LLM 猜的，而是有结构化可见性依据

---

## 5.7 `DiagnosisContext`

给诊断引擎的统一输入。

```python
class DiagnosisContext(BaseModel):
    profile_name: str
    scope: AnalysisScope
    signals: list[DiagnosticSignal] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    visibility: VisibilityAssessment | None = None
    knowledge_refs: list[str] = Field(default_factory=list)
```

这样无论 one-shot 还是 agent，都吃同一个 contract。

---

## 5.8 `ScopeDiagnosis`

平台级输出。

```python
class ScopeDiagnosis(BaseModel):
    scope_id: str
    verdict: str
    failure_point: str = ""
    root_cause: str = ""
    confidence: float = 0.0
    summary: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    investigation_trace: list[dict[str, Any]] = Field(default_factory=list)
```

---

# 6. Profile contract 设计

这一层决定以后怎么挂新场景。

## 6.1 `AnalysisProfile`

核心接口建议这样：

```python
class AnalysisProfile(Protocol):
    name: str

    def extract_records(self, input_path: str, options: AnalysisOptions) -> list[CaptureRecord]: ...
    def build_scopes(self, records: list[CaptureRecord], options: AnalysisOptions) -> list[AnalysisScope]: ...
    def annotate_signals(self, scope: AnalysisScope, records: list[CaptureRecord], options: AnalysisOptions) -> list[DiagnosticSignal]: ...
    def collect_evidence(self, scope: AnalysisScope, records: list[CaptureRecord], options: AnalysisOptions) -> list[EvidenceItem]: ...
    def assess_visibility(self, scope: AnalysisScope, records: list[CaptureRecord], options: AnalysisOptions) -> VisibilityAssessment: ...
    def build_diagnosis_context(self, scope, records, options) -> DiagnosisContext: ...
    def get_tools(self) -> list[ProfileTool]: ...
    def render_report(self, analysis_result) -> str: ...
```

---

## 6.2 `open5gs_5gc` profile 内部怎么映射

你现有实现几乎都能直接并入终态位置：

- **[records]** [extract_5gc_records](cci:1://file:///home/ailink/code/TraceWeaver/traceweaver/tshark/extract.py:216:0-308:5) -> `profiles/open5gs_5gc/extract/records.py`
- **[events]** [detect_events_for_record](cci:1://file:///home/ailink/code/TraceWeaver/traceweaver/events/identify.py:60:0-120:17) -> `profiles/open5gs_5gc/events/identify.py`
- **[UE assemble]** [group_ue_sessions](cci:1://file:///home/ailink/code/TraceWeaver/traceweaver/correlate/ue_sessions.py:22:0-143:5) -> `profiles/open5gs_5gc/assemble/ue.py`
- **[SBI correlate]** `pair_sbi_calls + correlate_sbi_to_sessions` -> `profiles/open5gs_5gc/assemble/sbi.py`
- **[PDU correlate]** `build_pdu_sessions_for_ue + correlate_pfcp_to_pdu` -> `profiles/open5gs_5gc/assemble/pdu.py`
- **[signals]** 现有 signal collector / annotator 迁入 `signals/annotators.py`
- **[prompt]** 5GC diagnosis prompt 迁入 `diagnosis/prompt.py`

---

# 7. 平台统一入口

这个要尽快落。

## 新统一入口

```python
analyze_capture(path, *, profile="open5gs_5gc", llm_provider=None, options=None) -> AnalysisResult
```

这是**唯一权威入口**。重构完成后，不再保留旧分析入口作为别名或包装。

## 平台主流程

```text
load profile
  -> extract_records
  -> build_scopes
  -> for each scope:
       annotate_signals
       collect_evidence
       assess_visibility
       build_diagnosis_context
       run diagnosis engine / agent
  -> render result
```

## 关键点

- **[平台只认 scope]**
- **[平台不认 UE/PDU]**
- **[平台不认 Open5GS]**
- **[平台不认 NAS/PFCP]**
- **[平台不认旧入口]** 所有历史入口、历史导入路径、历史 CLI 全部删除

这些都属于 profile。

---

# 8. Agent 架构怎么落在这个平台上

你现在最关心的是“做完整 agent 但不能绑 5GC”。  
所以 agent 必须建在 core contract 上。

## 8.1 Agent 输入

Agent 只接收：

- `DiagnosisContext`
- `ToolRegistry`
- `InvestigationPolicy`

## 8.2 Agent 状态

```python
class InvestigationState(BaseModel):
    scope_id: str
    round_index: int = 0
    hypotheses: list[dict[str, Any]] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    budget_remaining: int = 0
    termination_reason: str = ""
```

## 8.3 Agent 工具分类

### 平台通用工具
- **[tool]** `list_scopes`
- **[tool]** `get_scope_summary`
- **[tool]** `get_scope_timeline`
- **[tool]** `get_frame_detail`
- **[tool]** `get_visibility_assessment`
- **[tool]** `retrieve_knowledge`

### Profile 扩展工具
- **[5GC tool]** `get_sbi_calls`
- **[5GC tool]** `get_pdu_sessions`
- **[5GC tool]** `get_pfcp_messages`
- **[5GC tool]** `get_registration_path`

这样 agent 本体不绑定 5GC，只是某些 profile 多提供专用工具。

---

# 9. 现有文件迁移映射

这是最实际的部分。

## 9.1 直接归位到终态目录

- **[迁移]** [traceweaver/events/identify.py](cci:7://file:///home/ailink/code/TraceWeaver/traceweaver/events/identify.py:0:0-0:0)
  - -> `traceweaver/profiles/open5gs_5gc/events/identify.py`

- **[迁移]** [traceweaver/correlate/ue_sessions.py](cci:7://file:///home/ailink/code/TraceWeaver/traceweaver/correlate/ue_sessions.py:0:0-0:0)
  - -> `traceweaver/profiles/open5gs_5gc/assemble/ue.py`

- **[迁移]** [traceweaver/correlate/sbi.py](cci:7://file:///home/ailink/code/TraceWeaver/traceweaver/correlate/sbi.py:0:0-0:0)
  - -> `traceweaver/profiles/open5gs_5gc/assemble/sbi.py`

- **[迁移]** [traceweaver/correlate/pdu.py](cci:7://file:///home/ailink/code/TraceWeaver/traceweaver/correlate/pdu.py:0:0-0:0)
  - -> `traceweaver/profiles/open5gs_5gc/assemble/pdu.py`

- **[迁移]** [traceweaver/ingest/pdu.py](cci:7://file:///home/ailink/code/TraceWeaver/traceweaver/ingest/pdu.py:0:0-0:0)
  - -> `traceweaver/profiles/open5gs_5gc/extract/pdu.py` 或合并入 assemble

- **[迁移]** [traceweaver/diagnosis/llm_engine.py](cci:7://file:///home/ailink/code/TraceWeaver/traceweaver/diagnosis/llm_engine.py:0:0-0:0) 中 5GC prompt 构造部分
  - -> `traceweaver/profiles/open5gs_5gc/diagnosis/prompt.py`

---

## 9.2 直接重组为 core

- **[提升]** [traceweaver/tshark/extract.py](cci:7://file:///home/ailink/code/TraceWeaver/traceweaver/tshark/extract.py:0:0-0:0)
  - 拆成：
    - core 通用 tshark runner
    - profile 字段定义

- **[提升]** `LLMProvider`
  - 保持在 core

- **[提升]** output schema / parse / validator
  - 保持在 core

- **[提升]** diagnosis runner skeleton
  - 迁到 `core/analysis/engine.py`

---

## 9.3 直接删除的旧结构

- **[删除]** `traceweaver/ingest/records.py` 中以 `extract_5gc_*` 为中心的旧入口
- **[删除]** `traceweaver/ingest/sessions.py` 中以 `extract_ue_sessions` 为中心的旧入口
- **[删除]** `traceweaver/diagnosis/run.py` 中旧的顶层诊断编排入口
- **[删除]** 所有依赖旧模块路径的 import、测试引用、CLI 子命令实现
- **[删除]** 一切仅用于过渡的 wrapper、adapter、compat 目录与桥接代码

---

# 10. 哪些对象必须立刻去 5GC 化

这一步别拖。

## 必须立即抽象的平台对象

- **[必须]** `NormalizedRecord` -> `CaptureRecord`
- **[必须]** `DetectedEvent` -> `StructuredEvent`
- **[必须]** `SessionDiagnosis` 输出层 -> `ScopeDiagnosis`
- **[必须]** `DiagnosisReport` -> `AnalysisResult`
- **[必须]** 诊断输入 contract -> `DiagnosisContext`
- **[必须]** 后续 agent state / evidence / visibility 全部平台化
- **[必须]** 上述替换在同一轮重构中完成，旧对象不再作为公共接口残留

---

# 11. 哪些对象可以暂时留在 profile 内部

这些不用急着抽通用。

- **[可留]** [UESession](cci:2://file:///home/ailink/code/TraceWeaver/traceweaver/models/sessions.py:8:0-26:68)
- **[可留]** [PDUSessionFlow](cci:2://file:///home/ailink/code/TraceWeaver/traceweaver/models/pdu.py:20:0-33:60)
- **[可留]** [SBICall](cci:2://file:///home/ailink/code/TraceWeaver/traceweaver/models/sbi.py:3:0-22:35)
- **[可留]** [PFCPFlow](cci:2://file:///home/ailink/code/TraceWeaver/traceweaver/models/pdu.py:6:0-17:33)
- **[可留]** `RAN-UE-NGAP-ID / AMF-UE-NGAP-ID` 关联逻辑
- **[可留]** `nsmf-pdusession` / `nudm-*` / `nausf-auth` 这些 service heuristics

原则很简单：

> **内部算法对象可以继续 5GC-specific，但 profile 对外输出必须走平台 contract。**

---

# 12. 最推荐的迁移顺序

## 单次 Cutover 实施方式

这里不是“阶段性上线”，而是**在一个重构分支上一次性完成终态结构，然后整体切换**。

### 步骤 1 先搭终态目录与终态 contract

- **[做]** 一次性建立 `core/contracts`、`core/analysis`、`core/profile`、`core/agent`
- **[做]** 一次性建立 `profiles/open5gs_5gc/*` 全部目标目录
- **[做]** 先写终态 `AnalysisResult / AnalysisScope / DiagnosisContext / ScopeDiagnosis`

### 步骤 2 把现有算法直接搬到终态位置

- **[做]** UE/SBI/PDU/events/tshark 代码直接移动到终态目录
- **[做]** 在新位置完成 import 重写，而不是在旧位置留壳
- **[做]** prompt、signals、report 一次性收口到 profile 内部

### 步骤 3 把所有上层调用统一改写到终态入口

- **[做]** 所有 CLI 只调用 `analyze_capture`
- **[做]** 所有 diagnosis 流程只接收 `DiagnosisContext`
- **[做]** 所有测试只引用新模块路径和新 contract

### 步骤 4 删除旧结构并完成全量校验

- **[做]** 删除旧 `ingest / correlate / events / diagnosis` 中已被新结构替代的入口文件
- **[做]** 删除旧 CLI 子命令及其实现
- **[做]** 全量修正 import、类型引用、测试、文档
- **[做]** 以“代码库中不存在旧主干路径引用”为 cutover 完成标准

### Cutover 完成标准

- **[标准]** 代码库中不存在 compat / adapter / wrapper
- **[标准]** 代码库中不存在旧主干入口的存活引用
- **[标准]** 所有测试、CLI、文档只指向终态结构
- **[标准]** 后续开发只允许在终态结构上继续演进

---

# 13. CLI 怎么改

## 新 CLI 主命令

```bash
traceweaver analyze <pcap> --profile open5gs_5gc
```

## 新增辅助命令

```bash
traceweaver profiles list
traceweaver scopes list <pcap> --profile open5gs_5gc
traceweaver diagnose <pcap> --profile open5gs_5gc
traceweaver investigate <pcap> --profile open5gs_5gc
```

重构完成后，旧命令全部删除，不再保留别名。

---

# 14. 对 plan 的修正建议

你现在的 [plan](cci:9://file:///home/ailink/code/TraceWeaver/plan:0:0-0:0) 最大问题，是把 `Profile / Plugin / Agent` 放得太后了。  
这对“快速打 MVP”是对的，但对你当前这种 **代码大量由大模型生成** 的模式不合适。

## 我建议直接改成终态路线

### 终态里程碑 1 平台边界先定死
- core contracts
- profile runtime
- 统一 `analyze_capture`
- `open5gs_5gc` 作为首个官方 profile

### 终态里程碑 2 5GC 全能力直接落在终态位置
- 结构化抽取
- 会话组装
- 信号标注
- diagnosis
- report

### 终态里程碑 3 agent 直接落在终态 core 上
- investigation engine
- tool registry
- evidence/visibility-driven `INCONCLUSIVE`

也就是：

> **不是“先做 5GC 再平台化”，而是“直接按平台终态实现 5GC”。**

---

# 15. 最重要的架构约束

我建议你后面开发时强制遵守这几条。

## 约束 1 Core 禁止出现 5GC 术语

不能再在 core 新增：

- `UE`
- `PDU`
- `AMF`
- `SMF`
- `AUSF`
- `Open5GS`

## 约束 2 Agent 禁止直接依赖 profile 内部模型

不能让 agent 直接 import：

- [UESession](cci:2://file:///home/ailink/code/TraceWeaver/traceweaver/models/sessions.py:8:0-26:68)
- [PDUSessionFlow](cci:2://file:///home/ailink/code/TraceWeaver/traceweaver/models/pdu.py:20:0-33:60)
- [SBICall](cci:2://file:///home/ailink/code/TraceWeaver/traceweaver/models/sbi.py:3:0-22:35)

## 约束 3 Profile 对外只能通过平台 contract 出口

内部再复杂都可以，但对外要收敛成：

- `AnalysisScope`
- `DiagnosticSignal`
- `EvidenceItem`
- `DiagnosisContext`
- `ScopeDiagnosis`

## 约束 4 INCONCLUSIVE 必须建立在 visibility/evidence 上

不能只靠 prompt 文字约束。

## 约束 5 禁止引入任何过渡结构

不能新增：

- `compat`
- `adapter`
- `legacy_*`
- `v2` 外挂目录
- 旧接口到新接口的桥接壳

---

# 16. 最终判断

## 我建议你现在就按这个方向转

因为当前还处在一个 **可以翻边界、但还没深度固化** 的时间点：

- 5GC 数据工程已经有基础
- agent/tool schema 还没彻底铺开
- profile/plugin 还没有大规模沉没成本

这时候做“平台化翻转”，总代价是可控的。

## 如果现在不转

后面一旦继续在当前结构上做：

- agent
- tool calling
- RAG
- report schema
- case memory

你会发现所有东西都默认是 `5GC/Open5GS diagnosis system`，那时再抽平台会非常痛。

---

# 17. 我给你的直接建议

如果你现在要我给一句最执行导向的话，就是这个：

> **不要再继续扩当前 `traceweaver/correlate + diagnosis + ingest` 这条 5GC 主干了。直接把仓库切到 `core + profiles/open5gs_5gc` 的终态结构，旧结构整体删除。**

这一步做完，后面的“完整 agent 化”才值得。

# 完成状态

- **[已完成]** 平台化翻转方案已全部实现：
  - 目标架构：`core + profiles/open5gs_5gc`
  - Core contracts: `CaptureRecord`, `StructuredEvent`, `AnalysisScope`, `DiagnosticSignal`, `EvidenceItem`, `VisibilityAssessment`, `DiagnosisContext`, `ScopeDiagnosis`
  - Profile contract: `AnalysisProfile` 协议
  - 目录结构：终态结构已全部落成
  - CLI: `profiles list`, `scopes list`, `analyze`, `diagnose`, `investigate`
  - Agentic Investigation Engine: 已完成多轮 loop、LLM planner、LLM termination reconsideration

## Investigation Engine 详细状态

### 已实现的 Agent 能力
- **[完成]** `traceweaver/core/agent/engine.py` - 多轮 investigation loop (MAX_ROUNDS=3)
- **[完成]** `traceweaver/core/agent/planner.py` - 规则 + LLM 双模式 hypothesis ranking / tool selection
- **[完成]** `traceweaver/core/agent/prompts.py` - planner prompt + termination reconsideration prompt
- **[完成]** `traceweaver/core/agent/tools.py` - 工具注册表 + 结构化结果
- **[完成]** `traceweaver/profiles/open5gs_5gc/investigation.py` - profile 专属工具集
  - `scope_overview`
  - `visibility_analysis`
  - `evidence_focus`
  - `signal_focus`
  - `protocol_drilldown` - 协议下钻
  - `frame_targeting` - 帧级定位

### LLM 参与层次
1. **Diagnosis 阶段**: `llm_diagnose_session()` - LLM 主诊断引擎
2. **Planner 阶段**: `_rank_with_llm()` - LLM 参与 hypothesis ranking / tool selection
3. **Termination 阶段**: `reconsider_termination_with_llm()` - LLM 复核终止决策 + next action synthesis

### CLI 支持
```bash
# 基础 investigation (规则驱动)
traceweaver investigate file.pcapng --profile open5gs_5gc

# 带 LLM 增强的 investigation
traceweaver investigate file.pcapng --profile open5gs_5gc --model ollama/qwen2.5:14b

# 指定 scope 调查
traceweaver investigate file.pcapng --profile open5gs_5gc --scope-id ran-1__amf-2
```

### 测试结果
- 全量测试：`107 passed, 42 skipped`
- Investigation 专项测试：`4 passed` (含多轮 loop、scope_id 过滤、LLM planner、LLM termination 验证)

如果你要，我下一条可以继续直接给你：

## `一步到位重构实施清单`
按文件级粒度列出：

- **[先新建哪些文件]**
- **[先移动哪些现有文件]**
- **[哪些旧文件直接删]**
- **[哪些模型直接替换，不保留旧 contract]**
- **[第一批 patch 应该落哪几个文件]**

这个我可以继续按“准备开工”的粒度给。

---

# 18. 一步到位重构施工清单

## 第一批直接创建的终态文件

- **[core contracts]** `traceweaver/core/contracts/__init__.py`
- **[core contracts]** `traceweaver/core/contracts/record.py`
- **[core contracts]** `traceweaver/core/contracts/event.py`
- **[core contracts]** `traceweaver/core/contracts/scope.py`
- **[core contracts]** `traceweaver/core/contracts/signal.py`
- **[core contracts]** `traceweaver/core/contracts/evidence.py`
- **[core contracts]** `traceweaver/core/contracts/visibility.py`
- **[core contracts]** `traceweaver/core/contracts/diagnosis.py`
- **[core analysis]** `traceweaver/core/analysis/__init__.py`
- **[core analysis]** `traceweaver/core/analysis/options.py`
- **[core analysis]** `traceweaver/core/analysis/result.py`
- **[core analysis]** `traceweaver/core/analysis/engine.py`
- **[core profile]** `traceweaver/core/profile/__init__.py`
- **[core profile]** `traceweaver/core/profile/base.py`
- **[core profile]** `traceweaver/core/profile/registry.py`
- **[profiles]** `traceweaver/profiles/__init__.py`
- **[profiles]** `traceweaver/profiles/open5gs_5gc/__init__.py`
- **[profiles]** `traceweaver/profiles/open5gs_5gc/profile.py`

## 第一批直接修改的现有文件

- **[修改]** `traceweaver/cli.py`
- **[修改]** `traceweaver/__init__.py`
- **[修改]** `traceweaver/__main__.py`（如入口签名需要收口）

## 第二批直接迁移到终态位置的文件

- **[迁移]** `traceweaver/events/identify.py`
- **[迁移]** `traceweaver/correlate/ue_sessions.py`
- **[迁移]** `traceweaver/correlate/sbi.py`
- **[迁移]** `traceweaver/correlate/pdu.py`
- **[迁移]** `traceweaver/diagnosis/signals.py`
- **[迁移]** `traceweaver/diagnosis/engine.py`
- **[迁移]** `traceweaver/diagnosis/llm_engine.py`

## 第二批直接删除的旧入口

- **[删除]** `traceweaver/ingest/events.py`
- **[删除]** `traceweaver/ingest/records.py`
- **[删除]** `traceweaver/ingest/sessions.py`
- **[删除]** `traceweaver/ingest/sbi.py`
- **[删除]** `traceweaver/ingest/pdu.py`
- **[删除]** `traceweaver/diagnosis/run.py`
- **[删除]** `traceweaver/diagnosis/__init__.py` 中旧顶层导出
- **[删除]** `traceweaver/ingest/__init__.py` 中旧顶层导出

## 第三批必须同步修改的测试与文档

- **[测试]** `tests/test_diagnosis.py`
- **[测试]** `tests/test_extract_pdu.py`
- **[文档]** `HANDOVER.md`
- **[文档]** README / 快速开始 / CLI 示例

## 开发执行顺序

### 顺序 1 建 core 和 profile 骨架

- **[目标]** 让 `analyze_capture()` 可以跑通 `open5gs_5gc`

### 顺序 2 切换 CLI 到新命令体系

- **[目标]** 让用户入口只剩 `analyze / profiles / scopes / diagnose / investigate`

### 顺序 3 把 5GC 编排逻辑收口到 profile

- **[目标]** 不再从 CLI 触达 `ingest/*` 或 `diagnosis/run.py`

### 顺序 4 删除旧入口并修测试

- **[目标]** 代码库不存在旧主干入口的存活引用

## 当前马上开工的第一刀

- **[第一刀]** 创建 `core/contracts + core/analysis + core/profile`
- **[第一刀]** 创建 `profiles/open5gs_5gc/profile.py`
- **[第一刀]** 重写 `traceweaver/cli.py` 到终态入口