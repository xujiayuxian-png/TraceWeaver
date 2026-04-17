#!/usr/bin/env python3
"""
开放式实验 V2：更好的 in-context learning，测试高级 AI 的推理能力
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
print('开放式实验 V2：In-context Learning + 推理链')
print(f'测试文件: {test_file.name}')
print('='*80)

# Step 1: 提取原始 records
print('\n[1] 提取记录...')
records = extract_records(test_file)

# Step 2: 构建时间线（包含关键事件序列）
print('\n[2] 构建事件时间线...')
timeline = []
for r in records.records:
    event = {
        'frame': r.frame_number,
        'time': round(r.time_epoch, 3),
        'protocols': r.protocols,
    }
    # 提取关键 5GC 信息（从 fields 字典）
    f = r.fields
    info = []
    if r.src_ip and r.dst_ip:
        info.append(f"{r.src_ip} -> {r.dst_ip}")
    if f.get('ngap.msg_type'):
        info.append(f"NGAP:{f['ngap.msg_type']}")
    if f.get('nas_5gmm.msg_type'):
        info.append(f"NAS-5GMM:{f['nas_5gmm.msg_type']}")
    if f.get('nas_5gsm.msg_type'):
        info.append(f"NAS-5GSM:{f['nas_5gsm.msg_type']}")
    if f.get('http2.request_uri'):
        uri = f['http2.request_uri'][:60]
        method = f.get('http2.method', '?')
        info.append(f"HTTP:{method} {uri}")
    if f.get('http2.status'):
        info.append(f"STATUS:{f['http2.status']}")
    if f.get('pfcp.msg_type'):
        info.append(f"PFCP:{f['pfcp.msg_type']}")
    if f.get('pfcp.cause'):
        info.append(f"PFCP-CAUSE:{f['pfcp.cause']}")
    if f.get('ngap.ran_ue_ngap_id'):
        info.append(f"RAN-UE:{f['ngap.ran_ue_ngap_id']}")
    if f.get('ngap.amf_ue_ngap_id'):
        info.append(f"AMF-UE:{f['ngap.amf_ue_ngap_id']}")
        
    event['info'] = ' | '.join(info)
    timeline.append(event)

# 显示一些样例数据帮助调试
print(f'    样例记录: {timeline[0] if timeline else "N/A"}')

# 过滤 PDU Session 相关的帧（使用更宽泛的条件）
pdu_session_frames = [e for e in timeline if e.get('info') and any(k in e['info'] for k in ['PDU', 'pfcp', 'PFCP', '5GSM', 'SESSION', 'Session', 'Establishment', 'ESTABLISHMENT'])]
print(f'    总记录: {len(timeline)}')
print(f'    PDU Session 相关: {len(pdu_session_frames)}')

# 如果没有找到，显示一些实际数据看看
if not pdu_session_frames and timeline:
    print('    前5条记录的实际内容:')
    for e in timeline[:5]:
        print(f"      Frame {e['frame']}: {e['info'][:100] if e['info'] else 'N/A'}")

# Step 3: 开放式 Prompt with Chain-of-Thought
print('\n[3] 构建推理链 Prompt...')

system_prompt = """\
You are an expert network protocol analyst specializing in mobile core networks (5G/4G).

Analyze the provided packet capture chronologically. Look for:
1. **Protocol sequences**: Is there a complete request-response flow?
2. **Repetition patterns**: Are requests being retried? This usually indicates timeout/failure.
3. **Status codes**: HTTP 4xx/5xx or protocol-specific error codes.
4. **Missing responses**: Requests without corresponding success confirmations.

Think step by step:
- First, identify what protocol flow is attempting to occur
- Then, check if each step completes successfully
- Look for any retries, errors, or missing responses
- Determine where the flow breaks down, if at all

Provide structured output with your reasoning."""

# 构建时间线文本（PDU session 相关帧）
timeline_text = "Event Timeline (PDU Session Establishment focus):\n"
timeline_text += "-" * 120 + "\n"
timeline_text += f"{'Frame':<8} {'Time':<10} {'Event Details'}\n"
timeline_text += "-" * 120 + "\n"

# 展示关键帧（限制避免过长）
for e in pdu_session_frames[:30]:
    timeline_text += f"{e['frame']:<8} {e['time']:<10} {e['info']}\n"

output_schema = """\
Provide your analysis in this JSON format:

{
  "flow_identified": "what protocol flow appears to be happening (e.g., 'PDU Session Establishment')",
  "steps_observed": [
    {"step": "description of step", "frame": 123, "status": "success|retry|error|pending"}
  ],
  "repetitions_detected": [
    {"what": "what is being retried", "frames": [123, 456], "implication": "what retries usually mean"}
  ],
  "breakdown_point": "where the flow fails, or null if successful",
  "root_cause_hypothesis": "your best guess at what's wrong",
  "confidence": "high|medium|low",
  "reasoning_chain": "your step-by-step thinking process"
}"""

user_prompt = f"""{timeline_text}

{output_schema}

Think step by step about what you observe."""

print(f'    Timeline entries: {len(pdu_session_frames[:30])}')
print(f'    Prompt size: ~{len(user_prompt)} chars')

# Step 4: 调用 LLM with Chain-of-Thought
print('\n' + '='*80)
print('[4] 调用 LLM（推理链模式）...')
print('='*80)

response = llm.complete(system_prompt, user_prompt)

print('\n>>> LLM 原始输出:')
print('-'*80)
print(response)
print('-'*80)

# Step 5: 解析和评估
print('\n' + '='*80)
print('[5] 评估推理质量')
print('='*80)

try:
    result = json.loads(response)
    print(f"\n✓ 解析成功")
    print(f"\n推理结果:")
    print(f"  识别到的流程: {result.get('flow_identified', 'N/A')}")
    print(f"  观察到的步骤: {len(result.get('steps_observed', []))} 个")
    for step in result.get('steps_observed', [])[:5]:
        print(f"    - Frame {step.get('frame')}: {step.get('step')} [{step.get('status')}]")
    
    reps = result.get('repetitions_detected', [])
    if reps:
        print(f"  检测到的重试: {len(reps)} 处")
        for r in reps:
            print(f"    - {r.get('what')}: frames {r.get('frames')} → {r.get('implication')}")
    else:
        print(f"  检测到的重试: 无")
    
    print(f"  故障点: {result.get('breakdown_point', 'N/A')}")
    print(f"  根因假设: {result.get('root_cause_hypothesis', 'N/A')}")
    print(f"  置信度: {result.get('confidence', 'N/A')}")
    print(f"\n  推理链: {result.get('reasoning_chain', 'N/A')[:300]}...")
    
    # 评估准确性
    print(f"\n{'='*80}")
    print('准确性评估:')
    correct_flow = 'PDU' in str(result.get('flow_identified', '')).upper()
    has_repetitions = len(reps) > 0
    mentions_pfcp = 'PFCP' in str(result.get('root_cause_hypothesis', '')).upper() or \
                    'UPF' in str(result.get('root_cause_hypothesis', '')).upper()
    
    print(f"  ✓ 正确识别 PDU Session 流程: {correct_flow}")
    print(f"  ✓ 检测到重试模式: {has_repetitions}")
    print(f"  ✓ 提及 PFCP/UPF: {mentions_pfcp}")
    
    score = sum([correct_flow, has_repetitions, mentions_pfcp])
    print(f"\n  综合评分: {score}/3")
    if score == 3:
        print("  评价: 推理准确，成功识别根因！")
    elif score >= 2:
        print("  评价: 部分正确，有一定推理能力")
    else:
        print("  评价: 推理失败，需要更多领域知识")
        
except json.JSONDecodeError as e:
    print(f"\n✗ JSON 解析失败: {e}")
    print(f"  原始响应前 1000 字符:\n{response[:1000]}")
except Exception as e:
    print(f"\n✗ 错误: {e}")

print('\n' + '='*80)
print('实验完成')
print('='*80)
