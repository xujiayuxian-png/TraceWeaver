# TraceWeaver LLM 诊断实验

本目录包含一系列开放式实验，用于探索 LLM 在 5G 网络故障诊断中的真实能力。

## 实验列表

### 1. 基础诊断实验

| 文件 | 说明 |
|------|------|
| `show_llm_io.py` | 完整的单次诊断流程（记录提取 → Session 组装 → 信号生成 → LLM 诊断） |
| `show_llm_io_simple.py` | 简化版：手动构建信号列表，展示 Prompt 构造和 LLM 调用 |

### 2. Investigation 模式实验

| 文件 | 说明 |
|------|------|
| `show_investigation.py` | 标准 Investigation 流程（3 轮迭代，预设工具） |
| `show_open_investigation.py` | 开放式 Investigation：工具返回原始数据，LLM 自主推理 |
| `open_investigation_full_log.py` | 完整记录每轮输入输出到文件 |

### 3. 批量测试脚本

| 文件 | 说明 |
|------|------|
| `test_all_pcaps.py` | 批量测试所有 fixtures/pcap 文件 |
| `test_core_pcaps.py` | 测试核心 pcap 文件（6个典型案例） |

### 4. 开放式能力测试

| 文件 | 说明 |
|------|------|
| `open_experiment.py` | 极简开放式：最少预置知识，测试 LLM 从原始数据发现问题的能力 |
| `open_experiment_v2.py` | 改进版：加入 Chain-of-Thought 提示，更强的 in-context learning |

## 输出文件

- `outputs/investigation_full_io_log.txt` - 完整记录 3 轮 Investigation 的所有输入输出（20KB）
- `outputs/test_all_output.txt` - 批量测试所有 28 个 pcap 文件的完整结果（174KB）
- `outputs/test_core_output.txt` - 核心 6 个 pcap 文件的测试结果

## 使用的模型

所有实验默认使用：**ollama/qwen3.5:9b**

## 关键发现

### 当前 TraceWeaver 架构的特点
1. **信号层**: 100% 硬编码规则（T3580_RETRY, PFCP_ASSOCIATION_RETRY 等）
2. **诊断层**: LLM 做"格式转换"（把信号翻译成 human-readable 的 root_cause）
3. **Investigation 层**: 假设复用 diagnosis.root_cause，工具行为预定义

### 开放式实验的发现
**高级 AI 确实具备自主分析能力**：
- ✅ 从原始数据中发现重试模式（6 次 PDU Session Request）
- ✅ 识别定时器行为（16 秒间隔 = T3502 重传）
- ✅ 跨层推理（NAS 失败 ↔ SMF/UPF PFCP 问题）
- ✅ 生成具体可操作的建议（检查 F-SEID、N4 接口）

### 架构启示
当前设计过于保守，把 LLM 当作"填空器"。更好的架构可能是：
- 工具层 → 返回原始数据
- 推理层 → LLM 自主发现模式、生成假设
- 验证层 → 交叉检查 LLM 推理与原始数据

## 运行实验

```bash
# 进入实验目录
cd experiments

# 运行任意实验
python show_open_investigation.py

# 查看完整日志
cat outputs/investigation_full_io_log.txt
```

## 实验时间线

- 2026-04-17: 创建基础实验，验证单次诊断流程
- 2026-04-17: 实现 Investigation 模式，测试 3 轮迭代
- 2026-04-17: 开放式实验 V1/V2，测试 LLM 自主推理能力
- 2026-04-17: 完整记录实验，分析输入输出来源
