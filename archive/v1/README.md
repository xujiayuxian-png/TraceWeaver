# TraceWeaver v1 归档

本目录保存 v1 代码和相关资产，仅供 v2 重构过程中参考。**v2 不依赖本目录的任何代码**。

## 归档内容

```
archive/v1/
├── traceweaver/              v1 Python 包（core + profile + llm + cli）
├── tests/                    v1 测试代码（test_*.py）
├── experiments/              v1 LLM 实验脚本和输出
├── docs-reference/
│   ├── llm/                  v1 LLM 实验记录和 agent 设计提案
│   └── profiles/             v1 5GC profile 文档
└── pyproject.toml            v1 的 pyproject.toml
```

## v2 为何重构

v1 的核心矛盾：LLM 被放在规则链路末端做"解释器"，而不是诊断主体。详细分析见 v2 设计文档
`docs/design/platform-v2.md` 第一节。

## 可复用资产（v2 会引用）

以下资产**不在 archive/v1 中**，仍放在仓库根目录，供 v2 直接使用：

- `tests/fixtures/pcap/` — 28 个 5GC 场景的 pcap 样本
- `tests/fixtures/expected_diagnosis.json` — 基线期望结论
- `scripts/traceweaver_test_data.sh` — 测试数据生成脚本
- `docs/archive/plan/` — v1 的规划文档，含协议关联、平台架构等历史思考

## 参考时可读的 v1 文件

- `archive/v1/traceweaver/profiles/open5gs_5gc/extract/records.py` — tshark 抽取的字段清单（v2 写 5GC profile 时复用）
- `archive/v1/traceweaver/profiles/open5gs_5gc/assemble/` — UE/SBI/PDU 关联算法（v2 写 scope 规则时复用）
- `archive/v1/traceweaver/profiles/open5gs_5gc/events/identify.py` — NAS/NGAP 事件映射表
- `archive/v1/docs-reference/llm/2026-04-16-ollama-qwen3.5-9b-batch-report.md` — 9B 模型实测报告

## 不要做的事

- 不要把 v1 代码 import 进 v2
- 不要在 v2 写兼容 v1 的适配层
- 不要保留 v1 的 API/CLI 命名为了向后兼容
