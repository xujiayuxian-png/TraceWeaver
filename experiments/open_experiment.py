#!/usr/bin/env python3
"""
开放式实验：让 LLM 直接从原始 records 中发现问题
目标：最小化预设知识，测试 LLM 的真实分析能力
"""

import json
from pathlib import Path
from traceweaver.llm import LLMProvider, LLMConfig
from traceweaver.profiles.open5gs_5gc.extract.records import extract_records

config = LLMConfig(model='ollama/qwen3.5:9b', max_retries=2)
llm = LLMProvider(config)
FIXTURES = Path('d:/code/TraceWeaver/tests/fixtures/pcap')

# 测试文件：PFCP 失败案例
test_file = FIXTURES / '07_pfcp_failure.pcapng'

print('='*80)
print('开放式实验：LLM 直接从原始 records 分析')
print(f'测试文件: {test_file.name}')
print(f'LLM模型: ollama/qwen3.5:9b')
print('='*80)

# Step 1: 提取原始 records（不做任何 5GC 组装）
print('\n[1] 提取原始 records...')
records = extract_records(test_file)
print(f'    共 {len(records.records)} 条记录')

# Step 2: 选择关键字段（最小化预处理）
print('\n[2] 构建原始数据视图...')
raw_view = []
for r in records.records[:50]:  # 限制前50条避免 prompt 过长
    entry = {
        'frame': r.frame_number,
        'time': r.time_epoch,
        'protocol': r.protocols[0] if r.protocols else 'Unknown',
        'src': r.src_ip,
        'dst': r.dst_ip,
    }
    # 只保留非空的 5GC 相关字段，但不解释它们的含义
    if hasattr(r, 'ngap_msg_type') and r.ngap_msg_type:
        entry['ngap_msg'] = r.ngap_msg_type
    if hasattr(r, 'nas_5gmm_msg_type') and r.nas_5gmm_msg_type:
        entry['nas_5gmm'] = r.nas_5gmm_msg_type
    if hasattr(r, 'nas_5gsm_msg_type') and r.nas_5gsm_msg_type:
        entry['nas_5gsm'] = r.nas_5gsm_msg_type
    if hasattr(r, 'http2_request_uri') and r.http2_request_uri:
        entry['http_uri'] = r.http2_request_uri[:80]
    if hasattr(r, 'http2_status') and r.http2_status:
        entry['http_status'] = r.http2_status
    if hasattr(r, 'pfcp_msg_type') and r.pfcp_msg_type:
        entry['pfcp_msg'] = r.pfcp_msg_type
    if hasattr(r, 'ran_ue_ngap_id') and r.ran_ue_ngap_id:
        entry['ran_ue_id'] = r.ran_ue_ngap_id
    if hasattr(r, 'amf_ue_ngap_id') and r.amf_ue_ngap_id:
        entry['amf_ue_id'] = r.amf_ue_ngap_id
    raw_view.append(entry)

print(f'    构建 {len(raw_view)} 条记录视图')

# Step 3: 开放式 Prompt（最小化 5GC 知识）
print('\n[3] 构建开放式 Prompt...')

system_prompt = """\
You are a network protocol analyzer. You examine network packet captures and identify patterns, anomalies, and potential issues.

Your task:
1. Analyze the provided network records chronologically
2. Identify any unusual patterns, errors, or failures
3. Explain what appears to be happening in the network
4. Suggest what might be wrong, if anything

Important:
- Do not assume specific domain knowledge about 5G or mobile networks
- Base your analysis only on what you observe in the data
- Look for: error codes, repeated attempts, missing responses, timeouts
- Note any patterns that suggest a failure or problem

Provide your analysis in a structured format."""

# 将 records 格式化为文本表格
timeline_text = "Network Records (chronological):\n"
timeline_text += "-" * 100 + "\n"
timeline_text += f"{'Frame':<8} {'Time':<12} {'Protocol':<10} {'Src':<15} {'Dst':<15} {'Key Info'}\n"
timeline_text += "-" * 100 + "\n"

for entry in raw_view:
    key_info = []
    for k, v in entry.items():
        if k not in ['frame', 'time', 'protocol', 'src', 'dst'] and v:
            key_info.append(f"{k}={v}")
    info_str = ", ".join(key_info)[:50]
    timeline_text += f"{entry.get('frame', '?'):<8} {entry.get('time', 0):<12.6f} {entry.get('protocol', '?'):<10} {entry.get('src', '?'):<15} {entry.get('dst', '?'):<15} {info_str}\n"

output_schema = """\
Provide your analysis in this JSON format:

{
  "summary": "brief summary of what you observe",
  "patterns_detected": ["list of patterns or behaviors you noticed"],
  "anomalies": ["any anomalies, errors, or suspicious behaviors"],
  "potential_issues": ["what might be wrong, if anything"],
  "confidence": "high|medium|low",
  "reasoning": "explain your thought process"
}"""

user_prompt = f"""{timeline_text}

{output_schema}"""

print(f'    System prompt: {len(system_prompt)} chars')
print(f'    User prompt: {len(user_prompt)} chars')
print(f'    Total: ~{len(system_prompt) + len(user_prompt)} chars (~{(len(system_prompt) + len(user_prompt))//4} tokens)')

# Step 4: 调用 LLM
print('\n' + '='*80)
print('[4] 调用 LLM（开放式分析）...')
print('='*80)

response = llm.complete(system_prompt, user_prompt)

print('\n>>> LLM 原始输出:')
print('-'*80)
print(response)
print('-'*80)

# Step 5: 解析和对比
print('\n' + '='*80)
print('[5] 解析结果并与规则驱动方式对比')
print('='*80)

try:
    result = json.loads(response)
    print(f"\n开放式分析结果:")
    print(f"  摘要: {result.get('summary', 'N/A')}")
    print(f"  检测到的模式: {result.get('patterns_detected', [])}")
    print(f"  异常: {result.get('anomalies', [])}")
    print(f"  潜在问题: {result.get('potential_issues', [])}")
    print(f"  置信度: {result.get('confidence', 'N/A')}")
    print(f"  推理: {result.get('reasoning', 'N/A')[:200]}...")
except Exception as e:
    print(f"  解析错误: {e}")
    print(f"  原始响应: {response[:500]}")

# 对比：规则驱动的结果
print(f"\n对比 - 规则驱动分析结果:")
print(f"  判决: FAIL")
print(f"  失败点: PDU_SESSION_ESTABLISHMENT")
print(f"  根因: PDU Session Establishment failed due to persistent PFCP connectivity issues...")
print(f"  置信度: high")

print('\n' + '='*80)
print('实验完成')
print('='*80)
