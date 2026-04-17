# TraceWeaver v2 跨机交接

这是给**新机器上开新会话**的单点入口文档。目标：新 agent 读完本文件 + 本文件点到的 2–3 份核心文档后，不问额外问题就能接着干活。

> 如果你（agent）是第一次进这个仓库，**按下面 §1 的顺序读文件，别跳读**。  
> 如果你是用户，滚到最底下的 §8 复制粘贴给新 agent 用的启动 prompt。

---

## 1. 必读文件（按顺序）

1. **本文件** `HANDOVER.md` — 全局状态和决策汇总
2. **`docs/design/platform-v2.md`** — v2 架构设计（唯一事实源，~600 行）
3. **`docs/guides/python-packaging-profiles.md`** — Profile 打 pip 包的教程（用户要求的学习材料，agent 可粗读）
4. **`scripts/validate_tool_calling.py`** — 9B 基线 tool calling 验证脚本（M1 前置门槛）
5. `archive/v1/README.md` — v1 归档索引，只在需要参考 v1 资产时看

**不要读**：`archive/v1/` 里的任何代码，除非 platform-v2.md 明确指向某个文件作为迁移参考。v2 不依赖 v1。

---

## 2. 当前仓库状态快照

```
TraceWeaver/
├── HANDOVER.md                                  ← 你在这里
├── archive/v1/                                  ← v1 全部归档，只读参考
│   ├── README.md                                  归档索引
│   ├── traceweaver/                               v1 源码
│   ├── tests/ experiments/ docs-reference/        v1 其他资产
│   └── pyproject.toml                             v1 pyproject
├── docs/
│   ├── design/platform-v2.md                    ★ v2 架构（必读）
│   ├── guides/python-packaging-profiles.md      ★ 打包教程
│   └── archive/{HANDOVER.md,ISSUES.md,plan/}      v1 历史文档（参考）
├── scripts/
│   ├── traceweaver_test_data.sh                   测试数据生成脚本（复用）
│   └── validate_tool_calling.py                 ★ 9B tool calling 验证
├── tests/fixtures/                                28 个 pcap + expected_diagnosis.json（复用）
├── pyproject.toml                                 v2 空壳（name=traceweaver, version=0.0.0）
└── TraceWeaver.code-workspace
```

**`traceweaver/` 目录不存在**——M1 会从零新建。

**git 状态**：大量 `R` 记录，是 `git mv` 把 v1 代码迁入 `archive/v1/`；加几个 `??`（`HANDOVER.md`、`pyproject.toml`、`docs/design/`、`docs/guides/`、`scripts/validate_tool_calling.py`、`archive/v1/README.md`）是本轮新产物。**这些改动尚未 commit**，用户会自己决定何时 commit。

---

## 3. 已定的决策（不要再问用户）

| 主题 | 决策 | 依据 |
|------|------|------|
| 架构范式 | LLM-first，五层可插拔 + Case Memory 贯穿层 | `platform-v2.md` §3 |
| 基线 LLM | `ollama/qwen3.5:9b`（或同级 qwen3:9b / qwen2.5:9b） | 用户明确指定，对应 v1 实测报告 |
| LLM 接入层 | `litellm` 统一封装，支持 ollama / openai / 外部 MCP agent | 用户明确要求 |
| 结构化输出 | 严格 JSON schema + Pydantic 校验，1 次重试 | `platform-v2.md` §6 表格 |
| Profile 分发 | M1–M2 用本地目录优先（`$TRACEWEAVER_PROFILES_PATH`），pip 打包是后期可选 | 用户选 C（本地目录）优先 B（pip） |
| 多源 | M3 先做日志（pcap + log 联合），不做 metrics/trace | 用户明确"先只做日志" |
| 自我进化 | Case Memory 自动存（`--confirm` 时写 confirmed，否则 pending） | 用户同意推荐方案 |
| Agent 生态 | M5 通过 MCP server 暴露全部工具，不做专用 UI | 用户选 B |
| 外部 agent 作为智能 | `MCPAgentIntelligence` 把整个任务打包转交外部 agent | `platform-v2.md` §4 Layer 4 |
| v1 代码处理 | 全部归档到 `archive/v1/`，v2 不 import | 用户明确要求 |
| Tool calling 验证 | 写脚本让用户自己跑，**不接受伪 agent 模式** | 用户明确要求 |

---

## 4. 红线（用户反复强调，必须遵守）

1. ❌ 不保留 v1 代码兼容层
2. ❌ 不写"规则兜底 + LLM 补充"的混合诊断
3. ❌ 不在工具里做诊断判断（工具只返回事实）
4. ❌ 不在 core 里写协议/行业特定逻辑
5. ❌ 不让 core 依赖某个具体 profile
6. ❌ 不假设多模型轮值（M1 单后端）
7. ❌ 不做"半成品 M 阶段"（每个 M 都完整可用）
8. ❌ 不搞任何"中间方案"——用户原话："一插到底，不接受任何中间方案"

**行为准则**：当你不确定某个设计是否属于"中间方案"时，**停下来问用户**，不要自己选择折中。

---

## 5. 下一个动作（明确）

**当前卡点**：用户在换机器，**没跑过** `scripts/validate_tool_calling.py`。

**新会话开局第一件事**：
- 如果用户说"我已经跑了验证"或贴了脚本输出 → 按结果决定走 M1 还是调整方案
- 如果用户说"我还没跑"或没提 → **不要动代码**，先让用户按脚本文档说明跑一次

**验证脚本运行方式**（给用户抄的）：
```bash
cd /path/to/TraceWeaver
pip install 'litellm>=1.40' 'pydantic>=2.8'
ollama serve &
ollama pull qwen3:9b   # 或 qwen2.5:9b
python scripts/validate_tool_calling.py
# 想换模型：python scripts/validate_tool_calling.py --model ollama/qwen2.5:14b
```
输出：控制台摘要 + `.traceweaver/validate_tool_calling_<ts>.json`；退出码 0 = 通过，1 = 不通过，2 = 环境问题。

**验证通过后的 M1 第一步**（详细清单在 `platform-v2.md` §7 M1 小节）：
1. 新建 `traceweaver/` 空目录
2. 按 Layer 0 → 1 → 2 → 3 → 4 → 5 顺序建代码，先跑通主干（单个 fixture pcap 出结论）
3. 再补 5GC profile 的 5–7 个工具
4. 最后 28 个 fixture 全量回归

**验收标准**（M1）：
- `traceweaver analyze tests/fixtures/pcap/01_registration_success.pcapng --profile open5gs_5gc --model ollama/qwen3.5:9b` 能出结论
- 28 个 fixture 全部跑通，无崩溃
- 至少 10/16 canonical 样本 verdict 命中

---

## 6. 可复用的 v1 资产（M1 写 5GC profile 时会引用）

| 用途 | 路径 |
|------|------|
| tshark 字段清单 | `archive/v1/traceweaver/profiles/open5gs_5gc/extract/records.py` |
| UE/SBI/PDU 关联算法 | `archive/v1/traceweaver/profiles/open5gs_5gc/assemble/` |
| NAS/NGAP 事件映射表 | `archive/v1/traceweaver/profiles/open5gs_5gc/events/identify.py` |
| 28 个 pcap 样本（**不在 archive**，仍在根） | `tests/fixtures/pcap/` |
| 期望诊断基线（**不在 archive**，仍在根） | `tests/fixtures/expected_diagnosis.json` |
| 9B 实测报告 | `archive/v1/docs-reference/llm/2026-04-16-ollama-qwen3.5-9b-batch-report.md` |

**引用方式**：读出算法思路，**在 v2 里重写**（重写时顺带脱掉 v1 里所有规则兜底/signal 预消化的代码路径）。不要直接 import。

---

## 7. 本次会话产物清单（给用户 commit 用）

新文件：
- `HANDOVER.md`（本文件）
- `archive/v1/README.md`
- `docs/design/platform-v2.md`
- `docs/guides/python-packaging-profiles.md`
- `scripts/validate_tool_calling.py`
- `pyproject.toml`（v2 空壳，替换掉已归档的 v1 版本）

重命名（`git mv`，历史保留）：
- 整个 v1 `traceweaver/` → `archive/v1/traceweaver/`
- 整个 v1 `tests/test_*.py` → `archive/v1/tests/`（`tests/fixtures/` 留在根）
- 整个 v1 `experiments/` → `archive/v1/experiments/`
- `docs/llm/` → `archive/v1/docs-reference/llm/`
- `docs/profiles/` → `archive/v1/docs-reference/profiles/`
- 原 `pyproject.toml` → `archive/v1/pyproject.toml`

建议 commit message：
```
refactor: archive v1, introduce v2 platform design

- move v1 traceweaver/, tests/test_*.py, experiments/, docs/{llm,profiles}/
  into archive/v1/ (history preserved via git mv)
- add docs/design/platform-v2.md (layered LLM-first architecture)
- add docs/guides/python-packaging-profiles.md
- add scripts/validate_tool_calling.py (9b baseline gate)
- add new root pyproject.toml (v2 skeleton, version 0.0.0)

No v2 code yet; M1 starts after tool-calling validation passes.
```

---

## 8. 新会话启动 prompt（用户复制粘贴给新 agent）

```
项目：/path/to/TraceWeaver

请先读 HANDOVER.md，然后按它列出的顺序读 platform-v2.md。
读完回答我三个问题确认你理解了：
  1. 当前还有没有 traceweaver/ 源码？
  2. M1 开工的唯一门槛是什么？
  3. "不接受中间方案" 具体指的是哪几种做法？

回答正确后等我下一步指令。不要主动改任何代码。
```

如果新会话里你想直接推进 M1（假设验证已过），把上面 prompt 最后一句改成：
```
回答正确后，按 platform-v2.md §7 M1 小节的顺序开始实施。
开工前先把 M1 的文件清单（每个 .py 文件的路径 + 一句话职责）列给我确认，我同意后你才动手写代码。
```
