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

- **`ROADMAP.md`（项目根）** - 当前向前看的执行路线图（**首选**）
- `docs/profiles/open5gs_5gc.md` - Open5GS 5GC Profile 完整文档（如存在）
- `docs/llm/README.md` - LLM 诊断测试结果（如存在）
- `experiments/README.md` - 实验脚本说明（如存在）

## 归档时间

- 2026-04-17：v1 旧设计文档归档
- **2026-04-27：M3 收敛之后归档** —— `2026-04-27/` 子目录

## 2026-04-27 归档子目录

| 文档 | 原用途 | 归档原因 |
|------|--------|----------|
| `2026-04-27/HANDOVER.md` | v2 跨机交接信，里程碑 M1-M7 编号 | M3 收敛完毕，M4-M7 路径被 `ROADMAP.md` §4 重排取代（log/多源不再做） |
| `2026-04-27/REFACTOR_PLAN.md` | core/ 纯化重构计划（阶段 A-F） | 阶段 A/C 已落地；阶段 B/D/E/F 见 ROADMAP 持续改进与 M5'/M7' |
| `2026-04-27/REFACTOR_PLAN_HARD.md` | REFACTOR_PLAN 的硬核版本 | 同上 |
