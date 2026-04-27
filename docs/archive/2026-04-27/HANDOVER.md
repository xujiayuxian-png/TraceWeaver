> 📌 **此文档已于 2026-04-27 归档**。当前主路线图见 [`ROADMAP.md`](../../../ROADMAP.md)（项目根）。
>
> 本文档保留作为 M1-M3 落地的历史记录。其中关于 M4-M7 的计划（Extension/Log/CaseMemory/MCP）已被 ROADMAP §4 重排取代：
> - 原 M4 Extension/分发 → ROADMAP M5'
> - 原 M5 Log/多源 → **删除**（不进 builtin，详见 ROADMAP §3.5）
> - 原 M7 MCP → ROADMAP M4'
>
> 当本文档与 ROADMAP 冲突时，以 ROADMAP 为准。

---

# TraceWeaver v2 跨机交接

这是给**新机器上开新会话**的单点入口文档。目标：新 agent 读完本文件 + 本文件点到的 2–3 份核心文档后，不问额外问题就能接着干活。

> 如果你（agent）是第一次进这个仓库，**按下面 §1 的顺序读文件，别跳读**。
> 如果你是用户，滚到最底下的 §8 复制粘贴给新 agent 用的启动 prompt。

---

## 1. 必读文件（按顺序）

1. **本文件** `HANDOVER.md` — 全局状态和决策汇总
2. **`docs/design/platform-v2.md`** — v2 架构设计（唯一事实源，~600 行）
3. **`docs/guides/python-packaging-profiles.md`** — Profile 打 pip 包的教程（agent 可粗读）
4. **`scripts/validate_tool_calling.py`** — 9B 基线 tool calling 验证脚本（已通过，保留做回归）
5. **`scripts/run_m3_smoke.py`** — M3 冒烟脚本（**M3 硬门槛**），9 个 canonical pcap 9/9 过才算 M3 完成（覆盖注册/PDU/去注册/重试等场景）
6. **`scripts/run_m3_regression.py`** — M3 回归基线脚本，对 28 个 pcap 采样产出快照，无 pass/fail 门槛
7. `archive/v1/README.md` — v1 归档索引，只在需要参考 v1 资产时看

**不要读**：`archive/v1/` 里的任何代码，除非 platform-v2.md 明确指向某个文件作为迁移参考。v2 不依赖 v1。

---

## 2. 当前仓库状态快照

```
TraceWeaver/
├── HANDOVER.md                                  ← 你在这里
├── archive/v1/                                  ← v1 全部归档，只读参考
├── docs/
│   ├── design/platform-v2.md                    ★ v2 架构（必读）
│   ├── guides/python-packaging-profiles.md      ★ 打包教程
│   └── archive/                                   v1 历史文档
├── scripts/
│   ├── validate_tool_calling.py                   9B tool calling 基线验证
│   ├── run_m3_smoke.py                          ★ M3 硬门槛（9 canonical pcap 9/9）
│   ├── run_m3_regression.py                     ★ M3 回归基线（28 pcap 全量采样，无门槛）
│   └── m3_smoke_*.json / m3_regression_*.json    各次实验快照（见 §5 实验记录）
├── traceweaver/                                 ★ v2 源码（M1 + M2 + M3 已落）
│   ├── cli/                                     ★ M3：traceweaver analyze CLI
│   │   ├── __init__.py                            入口 + UTF-8 stdio 修复
│   │   ├── analyze.py                             analyze 子命令（profile→ingest→tool→kernel→格式化）
│   │   └── diagnose_result.py                     AgentResult 人类可读格式化
│   ├── core/
│   │   ├── types.py                               Message / ToolCall
│   │   ├── source/                                Record / SourceHandle / FakeSource / PcapSource
│   │   │   └── enrich.py                        ★ M3：Enricher 类型 + EnrichedSourceHandle 懒求值包装
│   │   ├── profile/                               Profile / YAML loader / 本地目录扫描
│   │   │   ├── base.py                          ★ M3：新增 ProfileEnricherSpec
│   │   │   └── runtime.py                       ★ M3：resolve_enrichers / ingest_for_profile / wrap_handle_for_profile / build_knowledge_store
│   │   ├── knowledge/                             KnowledgeStore 协议导出
│   │   ├── tools/
│   │   │   ├── __init__.py / registry.py          同 M2（协议与注册）
│   │   │   └── loader.py                        ★ M3：load_profile_tools 动态 import profile.yaml:tools
│   │   ├── intelligence/                          LLMIntelligence（新增 MiniMax reasoning_split + <think> 剥离）
│   │   └── kernel/                                AgentKernel（新增重复调用去重 + 收尾强制窗口）
│   └── profiles/                                ★ M3：内置 profile 包
│       ├── __init__.py
│       └── open5gs_5gc/                           ★ 5GC 参考 profile（参见 §6）
│           ├── profile.yaml                       source_config / enrichers / tools / knowledge / llm
│           ├── enrich.py                          NAS/NGAP/SBI/PFCP 字段→event/protocol_layer/cause
│           ├── fields.py                          tshark 字段列表 + 消息/原因码映射表
│           ├── tools/                             5 个 5GC 专用工具
│           │   ├── list_ue_sessions.py
│           │   ├── get_ue_timeline.py
│           │   ├── get_sbi_calls.py
│           │   ├── get_pfcp_exchanges.py
│           │   └── get_nas_cause_meaning.py
│           ├── prompts/system.md                  诊断 workflow + 工具使用规则 + 收尾条件
│           ├── schema/diagnosis.json              最终 JSON schema (verdict/evidence/...)
│           └── knowledge/                         5GMM / 5GSM 原因码 + 核心流程 cheat-sheet
├── tests/
│   ├── core/intelligence/                         20 用例（新增 <think> 剥离 / MiniMax reasoning_details）
│   ├── core/kernel/                               16 M1 用例 + 2 重复调用去重用例
│   ├── core/source/                               Fake + Pcap + EnrichedSourceHandle
│   ├── core/profile/                              YAML loader + 目录扫描 + runtime helper
│   ├── core/knowledge/                            FileKnowledgeStore
│   ├── core/tools/                                tool loader + registry（builtin 已迁至 traceweaver/builtin）
│   ├── cli/                                     ★ M3：traceweaver analyze CLI 集成测试
│   ├── profiles/open5gs_5gc/                    ★ M3：fields / enrich / tools / profile_loads 各自的单测
│   └── fixtures/
│       ├── profiles/minimal/                      M2 最小 profile
│       ├── pcap/ (28 canonical samples)            M3 smoke + regression 用
│       └── expected_diagnosis.json                v1 遗留基线（新 M3 流程不再消费）
├── pyproject.toml                                 v2（pydantic+litellm+pyyaml+pytest）
└── TraceWeaver.code-workspace
```

**git 状态**：v1 归档重命名 + M1/M2/M3 全部源码、测试、脚本、profile 目前都未 commit。用户自己决定何时 commit。`minimax.txt` 已在 `.gitignore`。

---

## 3. 已定的决策（不要再问用户）

| 主题 | 决策 | 依据 |
|------|------|------|
| 架构范式 | LLM-first，五层可插拔 + Case Memory 贯穿层 | `platform-v2.md` §3 |
| 基线 LLM | **`openai/qwen/qwen3.5-9b` @ LM Studio**（OpenAI 兼容端点 `http://127.0.0.1:1234/v1`） | 用户选型；Ollama 的 qwen3.5 chat template 残缺，无法用 |
| LLM 接入层 | `litellm` 统一封装，Layer 4 `LLMIntelligence` 做 provider 归一化 | 用户明确要求 |
| Qwen 原生 tool call 归一化 | `LLMIntelligence` 兜底从 `content` / `reasoning_content` 里抽 `<tool_call>...</tool_call>`（JSON 形 + XML 形），合成结构化 `tool_calls` | LM Studio 对 Qwen3 的默认 tool parser 残缺 |
| 结构化输出 | Kernel 做 required-keys 校验，不匹配时注入 corrective user turn，超 2 次返回 `schema_retry_exhausted` | `platform-v2.md` §6 表格的精简版 |
| Profile 分发 | M2–M3 用本地目录优先（`$TRACEWEAVER_PROFILES_PATH`），pip 打包是后期可选 | 用户选 C |
| 多源 | 先做日志（pcap + log 联合），不做 metrics/trace | 用户明确 |
| 自我进化 | Case Memory 自动存（`--confirm` 时写 confirmed，否则 pending） | 用户同意 |
| Agent 生态 | 通过 MCP server 暴露全部工具，不做专用 UI | 用户选 B |
| 外部 agent 作为智能 | `MCPAgentIntelligence` 把整个任务打包转交外部 agent | `platform-v2.md` §4 Layer 4 |
| v1 代码处理 | 全部归档到 `archive/v1/`，v2 不 import | 用户明确要求 |
| Tool calling 验证 | 写脚本让用户自己跑，**不接受伪 agent 模式** | 用户明确要求 |

---

## 4. 红线（用户反复强调，必须遵守）

1. ❌ 不保留 v1 代码兼容层
2. ❌ 不写"规则兜底 + LLM 补充"的混合诊断
3. ❌ 不在工具里做诊断判断（工具只返回事实，registry 会拒绝含 `verdict`/`root_cause`/`failure_point`/`confidence` 的 `ToolResult.data`）
4. ❌ 不在 core 里写协议/行业特定逻辑
5. ❌ 不让 core 依赖某个具体 profile
6. ❌ 不假设多模型轮值（M1 单后端）
7. ❌ 不做"半成品 M 阶段"（每个 M 都完整可用）
8. ❌ 不搞任何"中间方案"——用户原话："一插到底，不接受任何中间方案"

**行为准则**：当你不确定某个设计是否属于"中间方案"时，**停下来问用户**，不要自己选择折中。

---

## 5. 里程碑进度

⚠️ **用词提醒**：`platform-v2.md` §7 的原版 M1 把 Layer 0–5 全部打包（pcap source + 5GC profile + CLI + 28 fixture 回归，~3 周）。落地时用户同意把它拆成更细的 M 序列，当前编号：

| 本仓库 M# | 内容 | 对应 platform-v2.md 原 M |
|---|---|---|
| **M1（已完成）** | Agent Kernel + Intelligence + Tool 契约 & registry + Qwen 归一化 + 离线 + 冒烟 | 原 M1 的 Layer 2/3/4 部分 |
| **M2（已完成）** | Source 抽象 + FakeSource + PcapSource（tshark 可注入）+ Profile YAML + 本地目录扫描 + FileKnowledgeStore + 3 个 built-in tools + Kernel `run_with_profile` | 原 M1 的 Layer 0/1 + built-in tools |
| **M3（已完成）** | Record Enricher + EnrichedSourceHandle + Profile.enrichers runtime + Tool loader (profile 动态加载) + `traceweaver analyze` CLI + 5GC 参考 profile (fields/enrich/5 tools/prompts/schema/knowledge) + M3 smoke (9/9) + M3 regression baseline (28 pcaps) | 原 M1 尾部 |
| **M4（下一步）** | Extension 注册 + Profile pip 分发 + 开发者文档 | 原 M2 |
| M5 | LogSource + ComposedSource + pcap/log 联合诊断 | 原 M3 |
| M6 | Case Memory | 原 M4 |
| M7 | MCP server | 原 M5 |

### 当前执行口径（唯一）

- `platform-v2.md` 负责架构定义；本文件负责“当前仓库可执行现实”。
- 当前里程碑：M1、M2、M3 已完成；M4 进行中。
- 当前只保留 3 个脚本入口：
  - `scripts/validate_tool_calling.py`
  - `scripts/run_m3_smoke.py`
  - `scripts/run_m3_regression.py`
- M3 硬门槛：9 个 canonical pcap，`run_m3_smoke.py` 必须 9/9。
- M3 回归：`run_m3_regression.py` 只产快照，不做 pass/fail。

### 当前验证命令（可复现）

```powershell
# 1) 单元与集成
.venv\Scripts\python -m pytest tests\ -q

# 2) tool-calling 基线验证
.venv\Scripts\python scripts\validate_tool_calling.py

# 3) M3 smoke（硬门槛）
.venv\Scripts\python -u scripts\run_m3_smoke.py `
    --model "openai/MiniMax-M2.7" `
    --api-base "https://api.minimaxi.com/v1" `
    --temperature 0.2

# 4) M3 regression（快照）
.venv\Scripts\python -u scripts\run_m3_regression.py `
    --model "openai/MiniMax-M2.7" `
    --api-base "https://api.minimaxi.com/v1" `
    --temperature 0.2 `
    --report scripts\m3_regression_baseline.json
```

### 当前代码结构要点（以仓库为准）

- `traceweaver/core`: 协议、Kernel、registry/loader 等抽象层。
- `traceweaver/builtin`: 默认 source/tool/knowledge 的具体实现。
- `traceweaver/profiles/open5gs_5gc`: 参考 profile（enrichers + tools + prompts + schema + knowledge）。
- `traceweaver/cli/analyze.py`: `profile -> ingest(enrich) -> tool loading -> kernel` 唯一主链路。

---

## 6. 可复用的 v1 资产（M3 5GC profile 会重写这些）

| 用途 | 路径 |
|------|------|
| tshark 字段清单 | `archive/v1/traceweaver/profiles/open5gs_5gc/extract/records.py` |
| UE/SBI/PDU 关联算法 | `archive/v1/traceweaver/profiles/open5gs_5gc/assemble/` |
| NAS/NGAP 事件映射表 | `archive/v1/traceweaver/profiles/open5gs_5gc/events/identify.py` |
| tshark runner | `archive/v1/traceweaver/core/tshark/` |
| 28 个 pcap 样本（不在 archive） | `tests/fixtures/pcap/` |
| 期望诊断基线（不在 archive） | `tests/fixtures/expected_diagnosis.json` |
| 9B 实测报告 | `archive/v1/docs-reference/llm/2026-04-16-ollama-qwen3.5-9b-batch-report.md` |

**引用方式**：读出算法思路，**在 v2 里重写**。不要 import archive。

---

## 7. 落地过程中沉淀的工程经验（后来者避坑）

### 7.1 Tool spec 的描述字符必须稳定
同一个模型在 `temp=0` 下，对两个措辞不同但语义等价的工具描述会走出**截然不同**的路径。M1 调试时，只把 `"Return how many UE sessions exist"` 换成 `"Return the number of UE sessions"`，T2 从 2 轮 final 变成 5 轮陷死在 `search_knowledge`。

**后果**：`ToolSpec.description` 写好后不要随意雕花。改措辞相当于改实验变量。

### 7.2 `ToolCall.arguments_raw` 必须保留
provider 返回的 `function.arguments` 是 JSON 字符串。kernel 解析成 dict 再重新 `json.dumps` 序列化会改变空白/键顺序，有的 chat template 会因此给模型不同上下文。

**后果**：`ToolCall` 同时持有 `arguments`（dict，给工具用）和 `arguments_raw`（原串，回传给模型用）。

### 7.3 工具的空返回要给"退路提示"
`search_knowledge` miss 时只返回 `{"result": "no matching entry"}`，9B 模型会死循环换词搜。

**解法**（通用性好，不是凑分）：miss 时加 `hint: "...proceed with your best diagnosis using general knowledge..."`。这是真实工具也会做的用户体验设计。

### 7.4 LM Studio + Qwen3 的 tool-call XML 泄漏
Qwen3 训练原生的 `<tool_call><function=X><parameter=K>V</parameter></function></tool_call>` XML（或 JSON 变体）在 LM Studio 的 Default parser 下**不会**被翻译成结构化 `tool_calls`，它会留在 `content` / `reasoning_content` 里。

**解法**：`LLMIntelligence` 兜底解析（同时支持 XML 和 JSON 两种内部格式）。对已经返回结构化 `tool_calls` 的 provider 零副作用。

### 7.5 PowerShell UTF-8
Windows PowerShell 默认 GBK，脚本打 `✓`/`✘` 会 `UnicodeEncodeError` 并吃掉后续 stdout（包括报告路径）。每个顶层脚本入口加 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`。

### 7.6 Thinking mode 是隐形坑
Qwen3 家族默认开 thinking，`content` 会是空串（甚至 `"\n\n"`）而有效答案在 `reasoning_content`。关掉的方式因 provider 而异：
- ollama：`extra_body={"think": False}`
- LM Studio：`extra_body={"chat_template_kwargs": {"enable_thinking": False}}`（效果取决于 loaded chat template）

`LLMIntelligence._provider_kwargs` 已按模型前缀注入，但**当 chat template 不支持 kwargs 时仍可能无效**；此时依赖归一化 + `reasoning_content` fallback 抢救。

### 7.7 Stringified-JSON 工具参数（M2 新增）
9B Qwen 间歇地把 dict/array 参数序列化为 JSON 字符串（如 `"filter": "{}"` 而非 `"filter": {}`）。这是 provider 那侧的训练噪声，不是 chat template 坏了，单纯改 prompt 压不住。

**解法**（放在 Layer 2 `ToolRegistry._coerce`，不是在某个工具里打补丁）：当 `parameters_schema` 声明某参数是 `type: "object"` 或 `"array"`，如果收到字符串就先尝试 `json.loads` 并校验形状。通用鲁棒性修复，对已正确返回的 provider 零副作用。

### 7.8 Profile 的 system prompt 要"职业化"
M2 smoke 一开始 2/5 通过，不是因为工具坏，是因为 profile 的 system prompt 太模糊。9B 在一般性 prompt 下会"不确定是否拿够数据→再调一次工具"。
加上三条硬约束后 5/5：
1. filter 必须是"扁平 object"（含反例："不要嵌套在 fields 下，不要传字符串"）。
2. "拿到数据立刻出最终 JSON，不要再调工具"。
3. "同一个工具不要以略微不同的参数重复调用"。

这不是 prompt 调色，是 profile 作者必须承担的接口契约说明——作为 M3+ 写 5GC profile 时的模板要求。

### 7.9 提示词压不住的"收尾失败"要在 Kernel 解决（M3 新增）
M3 smoke 在 9B 上首次只 1/5 过。失败模式不是工具不对，而是 LLM 不会停：重复同样的 `list_ue_sessions → get_ue_timeline`，或到了最后一轮还在请求工具。这是能力短板，不是 profile 问题。

- **重复调用去重**：同一 `(name, canonical_args_json)` 第 2 次出现时，kernel 不再执行工具，直接返回 `{"error": "duplicate_call: ..."}`。对 LLM 相当于一条强提示。
- **收尾强制窗口**：`round_idx >= max_rounds - 1` 时，kernel 从 `IntelligenceRequest.tools` 清空所有工具，并注入一条 user turn（"Return the final JSON verdict now"）。LLM 没有工具可调，只能输出最终答案。

这两个改动在 profile 那侧零感知，是 kernel 的通用能力。配上 MiniMax-M2.7 能拿到 5/5；9B 仍受限于自身推理能力，但"烧光预算"已经不会发生。

### 7.10 MiniMax reasoning 模型的两件事（M3 新增）
- **`<think>...</think>` 混在 `content` 里**：默认模式 MiniMax 把思考直接塞 `content`。kernel 把 content 当 final_text 会崩（字段污染 + final_json 解析失败）。解法：`LLMIntelligence._parse_completion` 用 `_split_think_tags` 把 `<think>` 段搬到 `reasoning`。
- **`reasoning_split=True` 的输出结构**：启用后思考进入 `message.reasoning_details: [{text: ...}]`，content 干净。`_provider_kwargs` 对 `openai/MiniMax-*` 自动启用；`_extract_reasoning_details` 兼容抽取。
- **`temperature` 必须 >0**：MiniMax 要求 `temperature ∈ (0.0, 1.0]`；默认 0.0 会被拒。smoke/regression 脚本都暴露 `--temperature`（推荐 `0.2`）。
- **首轮很慢**：M2.7 首包常常 20–40s，PowerShell 在 `python` 下会把 stdout 缓存到整段结束再吐出来。脚本入口始终 `python -u` + 所有 `print(..., flush=True)`，否则看着像"挂了"其实在跑。

---

## 8. 新会话启动 prompt（用户复制粘贴给新 agent）

```
项目：/path/to/TraceWeaver

请先读 HANDOVER.md，然后按它列出的顺序读 platform-v2.md。
读完回答我三个问题确认你理解了：
  1. 当前已完成到哪个 M# 阶段？下一步 M# 是什么？交付物的边界是什么？
  2. LLM 基线是什么？M1/M2/M3 三个冒烟脚本分别跑什么？M3 硬门槛上哪个模型达标？
  3. §7 里的 10 条工程经验，哪几条是 M3 才沉淀的（即 M4 必须继承的前置条件）？

回答正确后等我下一步指令。不要主动改任何代码。
```

如果希望新会话继续 M4 实施（前提：已确认 M3 smoke 通过）：

```
回答正确后，按 HANDOVER.md §5 表格里的 M4 范围开始。
开工前先把 M4 的文件清单（每个 .py / .md 的路径 + 一句话职责）和
与 M3 已有接口（Profile / Enricher / Tool loader / CLI）的契合点贴出来让我审，
我同意后你才写代码。
```
