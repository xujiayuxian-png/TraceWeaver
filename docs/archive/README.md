# 归档文档

本目录包含 TraceWeaver 项目的历史设计文档、计划草案和问题记录，这些文档已不再反映当前架构，保留供参考。

## 归档原因

经过 2026-04-17 的架构重构和实验验证，以下文档的内容已不再准确：

### 设计文档（plan/）

| 文档 | 原用途 | 归档原因 |
|------|--------|----------|
| `5gc-mvp-roadmap.md` | 5GC MVP 路线图 | 实际实现已偏离原计划，当前核心功能已完成 |
| `cross-protocol-correlation.md` | 跨协议关联设计 | SBI/PFCP/NGAP 关联已实现，设计已固化在代码中 |
| `intelligence-first-architecture.md` | 智能优先架构 | 实际采用规则+LLM 混合架构，非纯 LLM 驱动 |
| `platform-architecture.md` | 平台架构设计 | 已实现，设计细节已过时 |
| `terminal-cutover-refactor-plan.md` | 终端切换重构 | 已完成，重构已落地 |
| `test-pcap-catalog.md` | 测试抓包目录 | 测试用例已稳定，目录由 fixtures 管理 |
| `test-pcap-checklist.md` | 测试检查清单 | 测试流程已自动化 |

### 根目录文档

| 文档 | 原用途 | 归档原因 |
|------|--------|----------|
| `HANDOVER.md` | 项目交接 | 交接已完成，当前状态见 `docs/profiles/open5gs_5gc.md` |
| `ISSUES.md` | 问题记录 | 历史问题已解决或已转 GitHub issues |
| `juge.md` | 评审记录 | 评审已完成，结论已落实 |
| `redo.md` | 重做计划 | 大重构已完成（core/profile 分离），计划已过期 |

## 当前有效文档

请参考以下文档获取最新信息：

- `docs/profiles/open5gs_5gc.md` - Open5GS 5GC Profile 完整文档
- `docs/llm/README.md` - LLM 诊断测试结果
- `experiments/README.md` - 实验脚本说明

## 归档时间

2026-04-17
