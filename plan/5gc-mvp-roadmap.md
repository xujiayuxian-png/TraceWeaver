# 从 5GC 切入的平台 MVP 路线图

> **架构理念**：智能优先。LLM 是主诊断引擎，结构化数据工程为所有模型提供高质量输入，
> 信号标注器替代重规则引擎，流程跟踪器替代重状态机。
> 详细架构设计见 `intelligence-first-architecture.md`。

## 1. 文档目标

本文档描述如何从 `5GC` 场景切入，逐步落地一个面向多领域的抓包分析工作流平台。

目标不是一开始做成"万能平台"，而是：

- 先用 `5GC / Open5GS` 场景打穿平台底座
- 做出一个真实可用的 MVP
- 在 MVP 稳定后，再扩展到更多 profile 和 Agent 能力

---

## 2. 产品目标分层

### 第一层目标：做出可用产品

面向 5GC 场景，支持离线输入 `pcap/pcapng`，能够围绕以下问题给出 LLM 驱动的诊断报告：

- UE 接入失败
- PDU Session 建立失败

首版 MVP 先证明两件事：

- 结构化时间线能稳定还原
- 诊断结论能被底层证据约束

`RAG`、小模型优化、平台化抽象都属于增强项，不能反过来拖慢 `M1/M2` 落地。

### 第二层目标：建立可复用的数据工程底座

在解决 5GC 问题的同时，形成以下通用能力：

- 结构化抽取（pcap → NormalizedRecord）
- 会话组装（records → UESession / PDUSessionFlow）
- 信号标注（session → signals）
- LLM 诊断（signals + timeline → diagnosis）
- 数据合约稳定（Pydantic 模型为后续平台化铺路）

### 第三层目标：为二期 Agent 化与平台化铺路

保证 MVP 输出具备以下特征：

- 结构化会话数据可直接暴露为 MCP/Agent 工具
- LLM 诊断引擎天然就是 Agent 推理内核
- 证据可追溯到帧号

---

## 3. MVP 范围定义

### 3.1 首个场景

- `open5gs_5gc`（Open5GS 参考实现下的 5GC 注册与 PDU Session 分析）

### 3.2 首期协议范围

- `NGAP`
- `NAS-5GS`
- `HTTP2 SBI`
- `PFCP`

### 3.3 首期问题范围

- 注册流程卡住（任意步骤超时）
- 鉴权失败（Authentication Failure/Reject）
- 安全模式失败（Security Mode Reject）
- Registration Reject（含 5GMM cause code）
- PDU Session Reject（含 5GSM cause code）
- PFCP Session 建立失败
- SBI 调用失败（HTTP 4xx/5xx）导致下游流程终止
- UE 去注册 / UE Context Release
- Service Reject

### 3.4 首期运行方式

- CLI 本地运行
- 模型接入：本地模型 / Ollama / OpenAI 兼容 API

### 3.5 首期输出形式

- JSON 结构化诊断结果
- Markdown 报告

### 3.6 技术栈

- **语言**：Python 3.11+
- **数据模型**：Pydantic v2
- **tshark 调用**：subprocess
- **LLM 集成**：litellm
- **RAG**：ChromaDB + sentence-transformers
- **CLI**：typer
- **测试**：pytest
- **包管理**：uv + pyproject.toml

### 3.7 测试数据

测试 pcap 采集清单见 `test-pcap-checklist.md`。P0 场景 5 份，P1 场景 5 份，P2 场景 4 份。

---

## 4. 总体阶段划分

MVP 拆为 5 个阶段（0-4），每个阶段形成可运行结果。

### 阶段 0：范围冻结与设计落图

确定切入边界，完成架构设计，准备测试数据。

### 阶段 1：结构化抽取 + 会话组装

建立从 pcap 到结构化会话时间线的完整链路。这是纯数据工程，不含诊断逻辑。

### 阶段 2：信号标注 + LLM 诊断

使系统从"能还原流程"升级到"能诊断问题"。**LLM 是主诊断引擎**，信号标注器提供辅助。

### 阶段 3：RAG 知识增强 + 报告输出

通过 RAG 显著提升小模型诊断质量，输出面向工程师的可读报告。

### 阶段 4：Profile 化与平台收口

把 5GC 能力整理成可复用的 profile，把平台与场景能力彻底分层。

---

## 5. 阶段 0：范围冻结与设计落图

### 目标

明确首版只解决一个高价值场景：5GC / Open5GS。

### 需要完成的事项

- 架构设计文档（`intelligence-first-architecture.md`、`platform-architecture.md`）
- MVP 路线图文档（本文档）
- 跨协议关联方案（`cross-protocol-correlation.md`）
- 测试 pcap 采集清单（`test-pcap-checklist.md`）
- 测试数据采集（至少 P0 的 5 份 pcap）
- 数据合约初稿（Pydantic 模型定义）

### 需要确定的设计项

- 首期协议字段清单（tshark 字段名）
- 首期事件清单（NAS message type 映射）
- 首期信号标注器清单
- Prompt 策略（大/中/小模型分层）
- 模型接入方式
- RAG 数据源范围

### 产出物

- 全套设计文档
- 测试 pcap 数据集
- Pydantic 数据合约定义

### 验收标准

- 能用一页图讲清楚数据链路
- 明确哪些属于一期，哪些属于二期
- 测试 pcap 覆盖 P0 全部 5 个场景

---

## 6. 阶段 1：结构化抽取 + 会话组装

### 目标

建立从 pcap 到结构化会话时间线的完整链路。这是纯数据工程，不含诊断逻辑。

### 需要开发的模块

- `traceweaver/ingest/` — 文件输入与元信息
- `traceweaver/tshark/` — tshark 调用与字段抽取
- `traceweaver/events/` — 事件识别（协议语义映射）
- `traceweaver/correlate/` — 跨协议会话关联
- `traceweaver/models/` — Pydantic 数据合约

### 重点实现内容

#### 1. 文件输入与元信息

- 单个 pcap/pcapng 输入
- 文件合法性校验
- 基础元信息读取（包数、时长、协议存在性）

#### 2. 一次性 tshark 字段抽取

单次 tshark 调用抽取所有目标协议的关键字段，输出 `NormalizedRecord[]`。

关键字段参见 `cross-protocol-correlation.md` 第 3 节。

#### 3. 事件识别

基于 NAS message type 的确定性映射（不是规则），覆盖以下事件：

**注册流程**：
- `REGISTRATION_REQUEST` / `REGISTRATION_ACCEPT` / `REGISTRATION_COMPLETE` / `REGISTRATION_REJECT`
- `AUTHENTICATION_REQUEST` / `AUTHENTICATION_RESPONSE` / `AUTHENTICATION_RESULT` / `AUTHENTICATION_FAILURE` / `AUTHENTICATION_REJECT`
- `SECURITY_MODE_COMMAND` / `SECURITY_MODE_COMPLETE` / `SECURITY_MODE_REJECT`
- `DEREGISTRATION_REQUEST_UE_ORIG` / `DEREGISTRATION_ACCEPT_UE_ORIG`
- `DEREGISTRATION_REQUEST_UE_TERM` / `DEREGISTRATION_ACCEPT_UE_TERM`
- `SERVICE_REJECT`
- `5GMM_STATUS`

**PDU Session 流程**：
- `PDU_SESSION_ESTABLISHMENT_REQUEST` / `PDU_SESSION_ESTABLISHMENT_ACCEPT` / `PDU_SESSION_ESTABLISHMENT_REJECT`
- `PDU_SESSION_MODIFICATION_REQUEST` / `PDU_SESSION_MODIFICATION_ACCEPT` / `PDU_SESSION_MODIFICATION_REJECT`
- `PDU_SESSION_RELEASE_REQUEST` / `PDU_SESSION_RELEASE_REJECT` / `PDU_SESSION_RELEASE_COMMAND` / `PDU_SESSION_RELEASE_COMPLETE`
- `5GSM_STATUS`

**SBI 事件**：由 HTTP2 method + path + status 构建，不需要固定映射。

**PFCP 事件**：由 pfcp.msg_type 构建。

#### 4. 跨协议会话关联

详细方案见 `cross-protocol-correlation.md`，分 5 步：

1. NGAP/NAS 按 `(RAN-UE-NGAP-ID, AMF-UE-NGAP-ID)` 分组
2. 从 NAS 提取 SUCI/SUPI
3. HTTP2 SBI 关联：
   - nudm-*/namf-comm：通过 URL path 中的 SUPI/SUCI 直接匹配到 UE Session（高置信度）
   - nausf-auth/nsmf-pdusession/npcf-*：通过已关联 NF IP + 时间窗口关联（中置信度）
   - 详见 `cross-protocol-correlation.md` 第 2.1a 节（基于 Open5GS 源码验证）
4. PDU Session 按 PDU Session ID 从 NAS 和 SBI 中组装
5. PFCP 通过推断 SMF IP + 时间窗口关联到 PDU Session

#### 5. 流程跟踪器

轻量的流程进度跟踪器（不是诊断状态机），输出：

- `current_step`：当前走到哪一步
- `completed_steps`：已完成的步骤
- `missing_steps`：预期但未出现的步骤
- `stuck_at`：如果超时，停在哪一步
- `anomalies`：异常跳转（跳过步骤、收到 Reject、重试）

支持超时检测。并发子流程（注册期间同时发起 PDU Session）作为信号标注（`anomaly: concurrent_pdu_during_registration`）交给 LLM 判断，而非在跟踪器内部处理。

### 产出物

- 可执行 CLI：读取 pcap，输出 UE Session 和 PDU Session 的结构化时间线（JSON）
- 5GC 协议字段配置
- Pydantic 数据合约完整定义

### 验收标准

- 能从 `01_registration_success.pcap` 输出完整注册时间线
- 能从 `02_registration_and_pdu_session_success.pcap` 输出注册 + PDU Session 时间线，SBI 和 PFCP 正确关联
- 能从 `03_registration_reject.pcap` 输出中断的时间线和 Reject 事件
- 多 UE 并发抓包中不同 UE 的帧不会混淆
- 抓包不完整时优雅降级（标记 `not_captured`），不崩溃
- 当关联存在多个候选对象时，输出关联歧义而非伪确定性时间线

阶段 1 的核心验收重心不是“所有场景都关联成功”，而是“高置信度场景正确、低置信度场景诚实降级”。

### 风险点

- tshark 字段名版本差异（见下方 tshark 版本兼容策略）
- nausf-auth/nsmf-pdusession/npcf-* 的 URL 中不含 SUPI（基于 Open5GS 源码验证），依赖 IP+时间窗口关联
- 跨协议关联在多 UE 并发 + 时间窗口重叠时可能误关联
- NGAP ID 复用导致 UE Session 混淆

### tshark 版本兼容策略

- **最低版本要求**：tshark 4.0+（确保 HTTP2 和 5GS NAS 解码完整）
- **字段名别名映射**：实现 `FieldAliasMap`，将不同版本的字段名映射到统一内部名
  - 例：`ngap.RAN_UE_NGAP_ID` vs `ngap.ran_ue_ngap_id` → 统一为 `ran_ue_ngap_id`
- **CI 测试**：使用固定版本 tshark Docker 镜像运行测试
- **运行时检查**：启动时输出 tshark 版本，低于最低版本时发出警告

---

## 7. 阶段 2：信号标注 + LLM 诊断

### 目标

使系统从"能还原流程"升级到"能诊断问题"。**LLM 是主诊断引擎**，信号标注器提供辅助。

### 需要开发的模块

- `traceweaver/signals/` — 信号标注器
- `traceweaver/llm/` — LLM Provider 抽象 + Prompt 模板 + 结构化输出校验
- `traceweaver/diagnosis/` — 诊断引擎编排

### 重点实现内容

#### 1. 信号标注器

10-15 个轻量标注器，每个 5-20 行代码。只标注**客观事实**，不做诊断判断：

- `annotate_reject_causes` — 标注所有 Reject/Failure 的 cause code
- `annotate_missing_steps` — 标注预期流程中缺失的步骤
- `annotate_timeouts` — 标注步骤间超时（可配置阈值）
- `annotate_sbi_errors` — 标注 HTTP 4xx/5xx 响应
- `annotate_pfcp_failures` — 标注 PFCP 失败 cause
- `annotate_retries` — 标注重复发送同类消息的重试行为
- `annotate_out_of_order` — 标注事件顺序异常
- `annotate_context_release` — 标注 UE Context Release
- `annotate_correlation_gaps` — 标注关联置信度低的环节
- `annotate_error_codes` — 标注 NAS/NGAP cause code 原始值

#### 2. LLM Provider 抽象

通过 litellm 统一接口，支持：

- 本地模型（llama.cpp / vLLM）
- Ollama
- OpenAI 兼容 API
- 自定义 API

#### 3. 分层 Prompt 策略

根据模型能力选择不同的 prompt 策略：

- **大模型（GPT-4/Claude 级）**：结构化时间线 + 信号标注 → 自由推理
- **中模型（70B 级）**：时间线 + 信号 + 分步引导 prompt
- **小模型（8B-14B）**：时间线 + 信号 + Chain-of-Thought 模板 + RAG 知识

所有模型共享同一份结构化数据，差异仅在 prompt 和知识注入深度。

#### 4. 结构化输出校验

对 LLM 输出做 Pydantic schema 校验，输出 `DiagnosisResult`：

- `verdict`：OK / FAIL / INCONCLUSIVE
- `failure_point`：流程卡在哪一步
- `root_cause`：推断的根因
- `confidence`：high / medium / low
- `evidence`：支持结论的证据（帧号 + 字段值）
- `suggestions`：排查建议
- `limitations`：抓包缺口、关联歧义、版本兼容限制

校验失败时自动重试（最多 2 次）或降级为结构化兜底输出。

实施原则：

- `schema` 合法不等于诊断可靠，必须同时校验结论是否引用有效证据
- 当关键推断建立在 `low_confidence` 关联上时，输出必须进入 `INCONCLUSIVE` 或带明确 `limitations`

### 产出物

- 信号标注器完整实现
- LLM 诊断引擎（含 Provider 抽象 + Prompt 模板 + 输出校验）
- CLI 命令：读取 pcap → 输出 LLM 诊断报告（JSON）

### 验收标准

- 对 `03_registration_reject.pcap` 能输出正确的失败诊断
- 对 `04_authentication_failure.pcap` 能识别鉴权失败并给出排查建议
- 大模型（GPT-4 级）在 P0 失败场景上的 `failure_point_correct` 和 `evidence_valid` 达到 > 90%
- 中模型（14B 级，如 Qwen2.5-14B）在 P0 失败场景上的 `failure_point_correct` 达到 > 60%（阶段 3 RAG 增强后提升）
- 8B 模型作为挑战目标，不作为最低可用基线
- LLM 输出 schema 校验通过率 > 95%

阶段 2 的评估重心优先放在“失败点定位”和“证据有效性”，
不把主观性更强的 `root_cause` 文案准确率当成唯一 KPI。

14B 级模型（如 `Qwen2.5-14B-Instruct`）为最低可用基线。
8B 模型作为挑战目标，但不保证诊断质量。

如果小模型诊断失败（schema 校验多次失败或 confidence=very_low），
则降级为纯信号标注输出：输出会话时间线 + 信号标注 + 流程跟踪状态，不包含 LLM 诊断结论。

### 风险点

- 小模型结构化输出能力弱，schema 校验失败率高
- LLM 幻觉：给出看似合理但与证据矛盾的结论
- Prompt 模板需要反复调优
- 不同模型的 token 限制可能导致长时间线被截断
- 8B 模型可能无法理解 5GC cause code 上下文含义，优先用 14B 模型验证端到端链路

---

## 8. 阶段 3：RAG 知识增强 + 报告输出

### 目标

通过 RAG 显著提升小模型诊断质量，输出面向工程师的可读报告。

### 需要开发的模块

- `traceweaver/rag/` — 知识库加载、embedding、检索
- `traceweaver/reports/` — 报告生成器

### 重点实现内容

#### 1. RAG 知识库

首期知识源（轻量级，不做重知识库）：

- **3GPP Cause Code 说明**：5GMM/5GSM cause code → 含义 + 常见触发场景
- **Open5GS 模块职责**：AMF/SMF/UPF/AUSF/UDM/PCF 的职责和交互关系
- **常见故障模式**：典型故障的症状 + 时间线特征 + 排查方向
- **SBI 接口说明**：各 SBI 服务用途和典型错误

检索策略：根据信号标注自动生成检索 query。

#### 2. 报告生成

- JSON 结构化报告（机器可读）
- Markdown 报告（人类可读），包含：
  - 问题摘要
  - 会话时间线
  - 信号标注
  - LLM 诊断结论
  - 证据链（帧号 + 字段值）
  - 排查建议

### 产出物

- RAG 知识库初版（向量化存储）
- JSON + Markdown 报告生成器
- 小模型诊断质量优化后的 prompt

### 验收标准

- RAG 增强后中模型（14B 级）的 `failure_point_correct` 提升到 > 75%，8B 模型提升到 > 60%
- 报告可直接发给工程师阅读，无需额外解释
- RAG 检索延迟 < 500ms

### 风险点

- RAG 检索质量依赖 embedding 模型
- 知识库文本过长可能污染 LLM 上下文
- 小模型即使有 RAG 增强，复杂场景仍可能不够（在评估框架中量化跟踪）

---

## 9. 阶段 4：Profile 化与平台收口

### 目标

把 5GC 能力整理成可复用的 profile，把平台与场景能力彻底分层。

### 需要开发的模块

- `traceweaver/profile/` — Profile 加载与装配
- `traceweaver/plugin/` — 插件注册
- `traceweaver/api/` — 对外统一接口

### 重点实现内容

#### 1. Profile 装配机制

通过 profile 配置决定：

- 启用哪些协议字段
- 使用哪些事件映射
- 加载哪些信号标注器
- 采用哪些 Prompt 模板
- 挂载哪些 RAG 知识包
- 使用哪套报告模板

#### 2. 对外统一接口

- `analyze_capture(pcap_path, profile, options) -> AnalysisResult`
- `list_sessions(pcap_path, profile) -> list[SessionSummary]`
- `get_session_timeline(session_id) -> SessionTimeline`
- `generate_report(analysis_result, format) -> Report`

#### 3. 为 Agent/MCP 化预留

Structured Extractor + Session Assembler 的输出可直接暴露为 MCP 工具。

### 产出物

- `open5gs_5gc` 正式 profile
- 插件注册与加载机制
- 平台统一调用接口

### 验收标准

- 平台主干与 5GC 领域逻辑分离清晰
- 可以不修改核心代码就替换 Prompt 模板和 RAG 知识包
- 后续新增 profile 时只需新增配置和知识包，不需重构核心链路

### 风险点

- Profile 机制设计过重
- 插件装配边界不清，造成平台主干污染

---

## 10. 里程碑

### M0：设计完成

对应阶段 0。完成全套设计文档，测试 pcap 就绪。

### M1：看见结构化时间线

对应阶段 1。CLI 输出 UE/PDU Session 时间线，跨协议关联生效，且低置信度关联会被显式暴露。

### M2：看见 LLM 诊断结论

对应阶段 2。LLM 能对失败抓包输出证据驱动诊断，大模型在 `failure_point_correct` 与 `evidence_valid` 上达到 > 90%。

### 诊断准确率评估框架

阶段 0 就定义评估方案，阶段 2 验收时自动执行：

1. **评估数据集**：对每个测试 pcap 准备 `expected_diagnosis.json`（人工标注的正确诊断）
2. **评分维度**：
   - `timeline_correct`：关键流程时间线是否正确还原
   - `correlation_honesty`：低置信度/不可关联场景是否被诚实标记，而不是强行归并
   - `verdict_correct`：verdict（OK/FAIL/INCONCLUSIVE）是否正确
   - `failure_point_correct`：失败点定位是否正确
   - `root_cause_relevant`：根因描述是否相关（允许表述差异）
   - `evidence_valid`：证据帧号是否存在且相关
3. **自动化**：通过 pytest 执行，输出每个维度的通过率
4. **报告格式**：生成 `diagnosis_eval_report.json`，包含每个 pcap 的各维度得分

> **评估约束**：阶段 2 不以单一“总准确率”作为唯一 KPI，
> 必须分开跟踪 `timeline_correct`、`failure_point_correct`、`evidence_valid`，否则容易掩盖关联错误被 LLM 文案“说圆了”的问题。

### M3：看见可用报告

对应阶段 3。小模型有 RAG 增强，Markdown 报告可直接交付。

### M4：看见平台雏形

对应阶段 4。5GC 以 profile 方式运行，核心平台与领域逻辑边界清晰。

---

## 11. 二期规划方向

当 `open5gs_5gc` profile 稳定后，再进入二期。

### 二期建议模块

- MCP adapter（让外部 Agent 调用 TraceWeaver）
- Agent 多轮分析（大模型主动请求追加 tshark 查询）
- Web/HTTP profile
- 音视频 profile
- 知识案例库（用户反馈 + 案例积累）

### 二期核心目标

- 让平台能被外部 Agent 当工具使用
- 让平台从单次分析扩展到多轮分析
- 让平台从 5GC 扩展到至少一个新领域

---

## 12. 开发优先级建议

### P0（阶段 1 核心）

- tshark 字段抽取
- 事件识别（NAS message type 映射）
- 跨协议会话关联
- 流程跟踪器
- Pydantic 数据合约

### P1（阶段 2 核心）

- 信号标注器
- LLM Provider 抽象
- Prompt 模板（分层策略）
- 结构化输出校验

### P2（阶段 3 核心）

- RAG 知识库
- 报告生成
- 小模型诊断优化

### P3（阶段 4 + 二期）

- Profile / Plugin 机制
- MCP / Agent adapter
- 新领域 profile

---

## 13. 资源投入建议

优先把时间花在：

- 协议字段梳理与 tshark 验证
- 跨协议关联实现与测试
- Prompt 模板调优（直接决定诊断质量）
- 测试 pcap 采集与验收

不要一开始花太多精力在：

- 重前端
- 通用 DSL
- 复杂 Agent 框架
- 花哨的可视化
- 过重的 Plugin/Profile 框架

---

## 14. 路线图结论

**核心策略：结构化数据工程 + LLM 智能诊断。**

- 用 5GC 场景把数据工程底座逼出来
- 用 LLM 作为主诊断引擎，而非堆砌规则
- 用信号标注器为小模型提供辅助，而非替代模型智能
- 在 MVP 稳定后，再推进 Profile 化和 Agent 多轮分析
