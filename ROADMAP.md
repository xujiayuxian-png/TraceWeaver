# TraceWeaver ROADMAP

> **此文档是当前向前看的执行路线图**，与 `HANDOVER.md`（跨机交接信）和
> `REFACTOR_PLAN.md` / `REFACTOR_PLAN_HARD.md`（已部分落地的内核纯化重构记录）
> 职责互补。
>
> 当三者冲突时，**以本文件为准**。

---

## §1 项目北极星

> **基于 tshark 的 LLM-first 通用诊断平台，profile / 工具 / 智能体可插拔，**
> **能作为 MCP 工具暴露给外部 agent 生态。**
>
> Open5GS 5GC 是参考实现，**不是项目本身**。
>
> 取舍：**单源（pcap）即可**。多源（pcap + log + metric + trace）属于
> "看起来通用、实际很重" 的范畴，与"小而精美"目标冲突，故**不进 builtin**；
> 未来谁需要谁写外部 source 包（见 §3.5）。

衡量项目是否朝目标推进的硬指标：

1. 加入一种新协议（任意 vendor 5GC、4G EPC、SIP/VoIP、SDN 控制面、应用层…）只需写一份 profile 包，**不改 core**。
2. 任何外部 agent（Claude、Cursor、自建 LangGraph 编排）能通过 MCP 直接调用 TraceWeaver 的工具，把它当作"看包诊断的智能体子系统"。
3. 新协议的 profile 可以作为独立 pip 包发布安装，**不需要 fork 主仓库**。
4. Source 协议保持"任何返回 `Record` 的实现都合法"——多源能力作为可选外部扩展存在，但不进入 core / builtin。

四点都做到，平台目标算落地。当前一项都没真正完成。

---

## §2 现状审计（基于 2026-04-27 代码，非文档惯性）

### 已落地

| 维度 | 证据 |
|---|---|
| `core/` 纯协议 + `builtin/` 实现分层 | `@d:\code\TraceWeaver\traceweaver\core\protocols.py`、`@d:\code\TraceWeaver\traceweaver\builtin\` —— 即 `REFACTOR_PLAN.md` 阶段 A 已完成 |
| LLM-first 闭环（tshark → enrich → tools → kernel → final JSON） | M1 + M2 + M3 |
| 工具只返事实、不下判断 | `summarize_capture` 只输出 `event_inventory / ue_overview / capture_signals`；`get_ue_timeline` 已删合成 hint —— 即 `REFACTOR_PLAN.md` 阶段 C 已完成 |
| Kernel 防护（重复调用拒绝 + schema retry + budget warning） | `@d:\code\TraceWeaver\traceweaver\core\kernel.py` |
| LLM 调用上限（max_tokens=12288 + timeout=300s） | `@d:\code\TraceWeaver\traceweaver\core\intelligence\litellm_adapter.py` |

### 未落地（关键）

| 维度 | 证据 |
|---|---|
| **MCP server / HTTP server**（外部 agent 接入） | `pyproject.toml` 有 `optional-dependencies.mcp-server` 占位但**零代码**；CLI 只有 `analyze` / `validate-profile` |
| **Profile entry_points 第三方分发** | `pyproject.toml` 无 `[project.entry-points]`；`core/profile/loader.py` 自己注释 "pip-packaged profiles (entry_points) are M4+" |
| **第二个 reference profile（验证协议无关性）** | 当前只有 Open5GS 5GC 一个 profile，无法证伪/证实"core 真的协议无关" |
| **ToolSpec 自动从 Pydantic 生成** | 6 个工具仍各自手写 JSON Schema —— 即 `REFACTOR_PLAN.md` 阶段 B 未做 |
| **Case Memory** / **RecordReplayIntelligence** 接入 | `recording/recorder.py` 2 KB 桩；CLI 未暴露 |

### 显式不做（与目标冲突）

| 维度 | 不做的理由 |
|---|---|
| **LogSource / ComposedSource**（多源联合诊断） | 用户当前数据采集场景没有 log；接口破坏性大（`ToolContext.source_handle → sources` 影响所有工具）；时间归并复杂；日志格式因 NF 而异，写正则会让 profile 维度膨胀。**作为外部 source 包扩展即可，不进 builtin**。详见 §3.5 |

### 已知 bug（唯一确认）

| ID | 描述 | 位置 |
|---|---|---|
| BUG-1 | `summarize_capture.ue_overview.events` 截前 50 条丢尾部，导致 capture 后段 DEREGISTRATION 等事件对 LLM 不可见（T8 失败根因） | `@d:\code\TraceWeaver\traceweaver\profiles\open5gs_5gc\tools\summarize_capture.py:7`（`_MAX_UE_EVENTS=50`） |

### Open5GS 冒烟现状

| 模型 | 通过 | 报告 |
|---|---|---|
| qwen3.5-9b @ LM Studio | 4/9 | `@d:\code\TraceWeaver\reports\smoke_full.json` |
| qwen3.5-14b @ LM Studio | 9/9（历史记忆，未当面复现） | 待回归确认 |

---

## §3 关键认知校正

1. **冒烟 4/9 不是平台问题，是 9B 模型在长 trace 推理上提早收手。**
   把 9/9 当作"M3 门槛红线"会逼向**对一个弱模型的 prompt / 工具过拟合**——
   这是用户明确反对的方向。**M3 contract 已经干净，不再以 9b 通过率推动改动。**

2. **真正卡住"通用平台"的不是冒烟，是 M4-M7 完全空白。**
   HANDOVER §5 表里的 M4 (Extension/分发)、M5 (Log)、M6 (Case Memory)、M7 (MCP) 一项都没动。

3. **唯一明确工具 bug 是 BUG-1**，要修；其余冒烟失败属于"LLM 推理保守 / 提前 final"，
   解法是模型升级 + 持续观察，**不是改工具结构**。

4. **用户红线（继承 HANDOVER §4）**：
   - 工具不下判断（`registry` 已强制拒绝含 `verdict/root_cause/failure_point/confidence` 的 ToolResult）
   - core 不依赖某个 profile
   - 不以"9b 9/9"作为推进 M4+ 的门槛
   - 不为单一 case 改 prompt 或硬编码 hint

5. **Log / 多源不进 builtin。**
   `Source` 协议（`@d:\code\TraceWeaver\traceweaver\core\protocols.py:44`）已经足够干净：
   任何返回 `Record(source="...", ...)` 的实现都合法。未来如果某个用户真要 pcap+log 联合诊断，
   他可以**自己写一个 ComposedSource 类作为外部包**，在他的 `profile.yaml` 里注册即可。
   `core` 完全不需要知道 log 的存在。**这才是真正的可插拔**。

   把 log 写进 builtin 反而把"是否多源"这个决定从用户手里抢走，强加给所有 profile 写作者——
   与"小而精美"原则相悖。

---

## §4 阶段重排（取代 HANDOVER 旧 M4-M7 的执行顺序）

> **原则：模型质量与平台能力解耦。**
>
> 9b 通过率不作为推进 M4+ 的前置门槛；冒烟用 14b 跑回归即可。

### F0 — 即时稳定化（≤ 1 天，不阻塞主线）

| ID | 任务 | 验收 |
|---|---|---|
| F0.1 | 修 BUG-1：`summarize_capture.ue_overview.events` 改为 `events_head[:25] + events_tail[-25:]` 或改成完整 `event_seq_pairs: list[[seq,event]]`（更紧凑），保持纯事实 | 测试覆盖 capture > 50 events 的尾部场景；T8 不再被截断 |
| F0.2 | 在 `HANDOVER.md` / `REFACTOR_PLAN.md` / `REFACTOR_PLAN_HARD.md` 顶部加一段"已落地状态"标注，指向本 ROADMAP | 三份旧文档不再误导新会话 |
| F0.3 | qwen3.5-14b 跑一遍 9 个冒烟，结果钉死为 `reports/baseline_qwen14b.json`，作为 M3 真实基线 | 后续模型选型有据可依 |

### M4' — MCP serve（约 2-3 天）

> **这是从"单 profile 脚手架"升级成"可被外部 agent 调用的子系统"的核心**。
> 接口零破坏，做完立刻有外部价值。

#### 交付物

```
traceweaver/
├── serve/
│   ├── __init__.py
│   ├── mcp.py                 # ToolRegistry → MCP server 适配
│   └── http.py                # 可选 FastAPI 兜底（同样接口）
└── cli/
    └── serve.py               # `traceweaver serve --transport stdio|sse|http`
```

#### 关键设计点

- 每个 `Tool` 的 `ToolSpec.to_openai_tool()` 已经接近 MCP `tool` 定义；适配代码 < 100 行
- 启动时同样走 `profile + ingest + enrich`，但**不进入 kernel 循环**——MCP 只暴露原始工具，循环交给外部 agent
- `pyproject.toml.optional-dependencies.mcp-server` 真接代码

#### 验收

- [ ] Claude Desktop 配置 `traceweaver serve --transport stdio`，能列出 7 个工具
- [ ] 外部 agent 调用 `summarize_capture` 返回与本地一致的 JSON
- [ ] `traceweaver serve --transport sse` HTTP 模式能被 curl 调用

### M5' — Profile entry_points 分发（约 1 天）

> 即原 HANDOVER M4，与 MCP 配套——MCP 暴露的工具是哪个 profile 提供的，由用户安装哪个 profile 包决定。

- `pyproject.toml` 加 `[project.entry-points."traceweaver.profiles"]`
- `core/profile/loader.py` 同时扫描"目录 + 已安装 distribution"两路
- `tests/fixtures/external_profile_pkg/` 写一份样例外部 profile 包，证明真的可装可发现

#### 验收

- [ ] `pip install ./tests/fixtures/external_profile_pkg` 后，`traceweaver analyze --profile fake_profile ...` 能跑
- [ ] 卸载后 profile 自动从列表消失

### M6' — 第二个 reference profile（约 3-5 天）

> **这是真正测试"core 是否协议无关"的硬指标。**
>
> 只有一个 profile 时，永远说不清楚 core 是真的通用还是隐性偏向 5GC。
> 写第二个完全不同协议栈的 profile，把所有为 5GC 私下打的补丁都暴露出来。

#### 候选协议（选一个，按上手成本排序）

| 协议 | 上手成本 | 验证价值 | tshark 支持 |
|---|---|---|---|
| **SIP / VoIP**（INVITE / 200 OK / BYE / 4xx-6xx） | 最低 | 中（应用层文本协议，与 5GC 二进制协议形态完全不同，能暴露 enricher 假设） | ✅ 原生 |
| **4G EPC NAS**（Attach / Service Request） | 中 | 高（与 5GC 同家族，暴露"5GC profile 是否硬编码了 5G 字段名"） | ✅ 原生 |
| **DNS 故障**（NXDOMAIN / SERVFAIL / 超时） | 最低 | 低（场景太轻，难以体现工具组合） | ✅ 原生 |

推荐 **SIP/VoIP**：与 5GC 形态差别最大，最能验证平台通用性，并且 SIP 实战场景普遍（IMS、企业 PBX 故障）。

#### 交付物

```
profiles_external/sip_voip/         # 作为外部 profile 包，验证 M5' entry_points
├── profile.yaml                      # display_filter: "sip"
├── enrich.py                         # SIP 字段 → event/method/status_code/call_id
├── tools/
│   ├── summarize_capture.py          # 中性事实信号：method 计数、4xx/5xx 计数、call 数
│   ├── list_calls.py                 # 按 Call-ID 列出会话
│   ├── get_call_timeline.py          # 单一 call 的全程消息
│   └── get_sip_response_meaning.py   # 状态码字典
├── prompts/system.md
├── schema/diagnosis.json
└── knowledge/sip_status_codes.md
```

#### 验收（也是对 core 的真正考验）

- [ ] 写 SIP profile 过程中，**core 一行不改**——如果改了就是 core 没真的通用，记录痛点
- [ ] SIP profile 通过 entry_points 安装，`traceweaver analyze --profile sip_voip *.pcap` 跑通
- [ ] 准备 3-5 个 SIP canonical pcap（成功 INVITE / 4xx 拒绝 / 5xx 服务器故障 / BYE 异常），跑通诊断
- [ ] MCP serve 暴露 SIP 工具，外部 agent 能用

### M7' — Case Memory（约 3-5 天，本期不展开）

- ChromaDB / sentence-transformers 真接代码（`pyproject.toml.optional-dependencies.case-memory` 已占位）
- `--confirm` 写 confirmed 案例；否则 pending
- 在 `IntelligenceRequest` 之前注入 top-K 相似案例作为 system prompt 段
- 验收脚本：相同 capture 第二次跑，能命中第一次的 confirmed 答案并加速 / 提质

### 永远不做（除非项目定位变化）

- ❌ **LogSource / ComposedSource 进 builtin**：保持单源接口，多源由用户写外部包
- ❌ **metrics / trace source**：理由同上
- ❌ **专用 UI**（HANDOVER §3 已定）：通过 MCP 接入用户已有的 agent UI
- ❌ **多模型轮值 / 投票**：单后端，让 LLM 完整推理

### 持续（不阻塞主线）— 模型 / prompt 调优

- qwen3.5-14b 作为 M3 baseline；9b 作为"轻量模型可选项"
- 不针对单个 case 做 prompt 硬规则
- 如果发现某类信号普遍漏看，**只在 `capture_signals` 里加纯计数字段**（不加 verdict / 不加 likely_*）

### 持续（不阻塞主线）— Open5GS profile 数据完整性

> **原则：默认尝试解析，不要假设"加密就看不到"而归因 LLM 推理失败。**
>
> 任何"capture 里看不到某个事件"的现象，先核查 tshark 提取层是否漏了配置，
> 再核查 enricher 字段映射是否漏了消息类型，最后才考虑 LLM 推理问题。

| 改进项 | 说明 |
|---|---|
| **NAS 解密配置** | Open5GS 默认用 NIA0/NEA0（null integrity / null ciphering），SECURITY_MODE_COMMAND 之后的 NAS 报文（如 `REGISTRATION_ACCEPT`、`PDU_SESSION_ESTABLISHMENT_ACCEPT/REJECT`）在抓包里**应当是明文可见**。如果实际工具看不到，先检查 `profile.yaml.source_config.pcap` 是否需要追加 `tshark -o "nas-5gs.null_decipher:TRUE"` 等 prefs；用真 key 加密的 capture 则需要 KAMF 配置。**不要用"加密看不到"作为 LLM 误判的解释**。 |
| **enricher 完整性核查** | 用 `events_truncated_count > 0` 之外的另一个角度：拿 9 个 canonical pcap，对每个 capture 跑 `tshark -G fields` 列出实际出现的 `nas-5gs.mm.message_type` / `nas-5gs.sm.message_type` 整数集合，与 `EVENT_MM_MAP` / `EVENT_SM_MAP` 取差集。差集非空说明 enricher 漏了消息类型，事件会以 "未命名" 漏给 LLM。 |
| **PDU session 维度的 capture_signals** | 当前 `capture_signals` 已有 `pdu_session_establishment_request_count / accept_count / reject_count`，但缺 `pdu_session_request_without_terminal` 之外的 per-session 维度（同一 capture 多 PDU 时，请求和接受的对应关系）。如果发现 LLM 在多 PDU 场景下普遍漏判，再补——**不为单 case 改**。 |

---

## §5 红线（继承 HANDOVER §4）

1. ❌ 工具里不做诊断判断（registry 已强制拒绝含 verdict/root_cause/failure_point/confidence 的 ToolResult.data）
2. ❌ core 不依赖某个 profile
3. ❌ 不以 "9b 9/9" 作为推进 M4+ 的门槛
4. ❌ 不为单一 case 改 prompt 或加硬编码 hint
5. ❌ 不保留 v1 兼容层
6. ❌ 不写"规则兜底 + LLM 补充"的混合诊断
7. ❌ 不做"半成品 M 阶段"——每个 M' 完整可用才算落地
8. ❌ 不把 log / metric / trace 写进 builtin（保持单源接口，多源作为外部包扩展）

---

## §6 立即行动 checklist

按时间序，每条都可独立验收：

- [ ] **F0.1** `summarize_capture` 截断 bug 修复
  - 改 `_MAX_UE_EVENTS` 策略为 head+tail 或全量 seq 列表
  - 单元测试：构造 > 50 events 的 fake handle，断言尾部 DEREGISTRATION_REQUEST 在 ue_overview 中可见
  - 不动 prompt、不动其他工具

- [ ] **F0.2** 文档状态标注
  - `HANDOVER.md` 顶部加 "📌 当前主路线图见 `ROADMAP.md`"
  - `REFACTOR_PLAN.md` / `REFACTOR_PLAN_HARD.md` 顶部加 "✅ 阶段 A/C 已落地；阶段 B/D/E/F 见 ROADMAP §4"
  - 不删除旧文档，只追加状态行

- [ ] **F0.3** 14b 真实基线
  - 在 LM Studio 切到 qwen3.5-14b
  - 跑 `scripts/run_m3_smoke.py` 全量
  - 输出 `reports/baseline_qwen14b.json`，README 引用此基线

- [ ] **M4' Kickoff**：动手前先调研 `mcp` Python SDK 的最小可运行示例，确认 stdio / sse 两种 transport 都能跑通，再开始包装 `ToolRegistry`

完成 F0.* 后才进入 M4'；M4' 完成后才进入 M5'；以此类推。

**M4'-M6' 总计 6-9 天可完成**——届时项目从"单 profile 脚手架"真正升级成
"可被外部 agent 调用、协议无关、第三方可分发的诊断平台"。

---

## §7 文档归位

| 文件 | 职责 | 何时读 |
|---|---|---|
| `HANDOVER.md` | 跨机交接信，"在哪/装什么/怎么跑" | 新机器、新会话第一次进项目 |
| `REFACTOR_PLAN.md` | 内核纯化重构记录（已部分落地） | 想了解 core/builtin 分层史 |
| `REFACTOR_PLAN_HARD.md` | 同上的硬版本 | 同上 |
| **`ROADMAP.md`（本文件）** | **当前向前看的执行计划** | **每次开工前** |
