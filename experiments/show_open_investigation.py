#!/usr/bin/env python3
"""
开放式 Investigation：工具返回原始数据，LLM 主导推理
"""

import json
from pathlib import Path
from traceweaver.llm import LLMProvider, LLMConfig
from traceweaver.profiles.open5gs_5gc.extract.records import extract_records
from traceweaver.profiles.open5gs_5gc.assemble import group_ue_sessions, pair_sbi_calls, correlate_sbi_to_sessions
from traceweaver.profiles.open5gs_5gc.domain.diagnosis import DiagnosticSignal

config = LLMConfig(model='ollama/qwen3.5:9b', max_retries=2)
llm = LLMProvider(config)
FIXTURES = Path('d:/code/TraceWeaver/tests/fixtures/pcap')

test_file = FIXTURES / '07_pfcp_failure.pcapng'

print('='*80)
print('开放式 Investigation：LLM 主导推理')
print(f'测试文件: {test_file.name}')
print('='*80)

# Step 1: 提取原始数据
print('\n[1] 提取原始 records...')
records = extract_records(test_file)
print(f'    共 {len(records.records)} 条记录')

# Step 2: 组装 Session（保留原始数据引用）
print('\n[2] 组装 UE Sessions...')
sessions = group_ue_sessions(records)
correlate_sbi_to_sessions(pair_sbi_calls(records), sessions)
print(f'    共 {len(sessions)} 个 session')

# 选择第一个有 PDU session 的
session = None
for s in sessions:
    if s.pdu_sessions:
        session = s
        break
if not session:
    session = sessions[0] if sessions else None

if not session:
    print("  没有可用的 session")
    exit(1)

print(f'\n[3] 选择 Session: {session.session_id}')
print(f'    RAN-UE: {session.ran_ue_ngap_id}, AMF-UE: {session.amf_ue_ngap_id}')
print(f'    事件数: {session.event_count}, PDU sessions: {len(session.pdu_sessions)}')

# Step 3: 开放式 Investigation 模拟
print('\n' + '='*80)
print('[4] 开放式 Investigation（3轮迭代）')
print('='*80)

# 构建时间线（只包含原始信息，不解释含义）
def build_raw_timeline(session):
    """构建原始时间线，保留字段但不解释含义"""
    lines = []
    for ev in session.events:
        info = {
            'frame': ev.frame_number,
            'time': round(ev.time_epoch, 3),
            'protocol': ev.protocol,
        }
        if ev.event_name:
            info['event'] = ev.event_name
        if ev.cause is not None:
            info['cause'] = ev.cause
        if ev.pdu_session_id:
            info['pdu_id'] = ev.pdu_session_id
        lines.append(info)
    return lines

def build_sbi_raw(session):
    """原始 SBI 调用数据"""
    calls = []
    for c in session.sbi_calls:
        info = {
            'frame': c.request_frame,
            'method': c.method,
            'path': c.path[:60] if c.path else None,
            'service': c.service,
            'dst': c.dst_ip,
            'status': c.status,
        }
        calls.append(info)
    return calls

def build_pfcp_raw(pdu):
    """原始 PFCP 数据"""
    flows = []
    for f in pdu.pfcp_flows:
        info = {
            'frame': f.frame_number,
            'msg_type': f.msg_type,
            'cause': f.cause,
            'src': f.src_ip,
            'dst': f.dst_ip,
        }
        flows.append(info)
    return flows

# 获取 PDU session 数据
pdu = session.pdu_sessions[0] if session.pdu_sessions else None

# Round 1: 全局概览
print('\n--- Round 1: 全局概览 ---')
print('  Tool: scope_overview')
print('  返回原始数据（不解释）:')

raw_timeline = build_raw_timeline(session)
raw_sbi = build_sbi_raw(session)
raw_pfcp = build_pfcp_raw(pdu) if pdu else []

print(f'    - 事件时间线: {len(raw_timeline)} 条')
print(f'    - SBI 调用: {len(raw_sbi)} 条')
print(f'    - PFCP 流: {len(raw_pfcp)} 条')

# 构建 LLM prompt 进行开放式分析
system_prompt = """\
You are analyzing a 5G network capture. I will provide you with raw protocol data.

Your task in each round:
1. Observe the patterns in the data
2. Identify what looks unusual or problematic
3. Formulate hypotheses about what might be happening
4. Suggest what specific data you need to see next to confirm/disprove your hypotheses

Do not assume I will tell you what is wrong. Use your own reasoning based on the data.

Key things to look for:
- Repeated messages (retries)
- Missing responses
- Error codes (4xx, 5xx, or protocol-specific)
- Time gaps between related events
- Protocol sequences that seem incomplete"""

round1_data = {
    'round': 1,
    'scope': session.session_id,
    'summary': {
        'total_events': len(raw_timeline),
        'total_sbi_calls': len(raw_sbi),
        'total_pfcp_flows': len(raw_pfcp),
    },
    'sample_events': raw_timeline[:15],
    'sample_sbi': raw_sbi[:5],
    'sample_pfcp': raw_pfcp[:5] if raw_pfcp else [],
}

user_prompt_r1 = f"""Round 1 Analysis

Here is a summary of a UE session:
{json.dumps(round1_data, indent=2, ensure_ascii=False)}

Based on this sample data:
1. What protocol flows do you observe?
2. What patterns or anomalies do you notice?
3. Form 2-3 hypotheses about what might be happening (normal vs problematic)
4. What specific data would help you determine which hypothesis is correct?

Provide your analysis in JSON format with these fields:
- observations: list of what you see
- patterns: list of patterns detected
- hypotheses: list of {{
    "hypothesis": "description",
    "confidence": "high/medium/low",
    "test": "what data would confirm or refute this"
  }}
- next_data_needed: list of specific data points you want to examine"""

print('\n  >> Calling LLM for Round 1 reasoning...')
resp_r1 = llm.complete(system_prompt, user_prompt_r1)
print('\n  >> LLM Round 1 Response:')
print('  ' + '-'*76)
lines_r1 = resp_r1.split('\n')
for line in lines_r1[:30]:
    print(f'  {line}')
if len(lines_r1) > 30:
    print(f'  ... ({len(lines_r1) - 30} more lines)')

# Round 2: 根据 LLM 请求的数据，提供详细分析
print('\n--- Round 2: 深度钻取 ---')
print('  Tool: protocol_drilldown (根据 Round 1 的 next_data_needed)')

# 模拟：LLM 要求看 PDU Session Establishment 相关的帧
# 提供完整的时间线，强调重复和缺失

print('  提供: 完整事件时间线 + SBI 4xx 错误 + PFCP 重试模式')

# 找出关键模式
sbi_4xx = [c for c in raw_sbi if c.get('status') and 400 <= c.get('status') < 500]
pfcp_establishment = [f for f in raw_pfcp if 'Establishment' in str(f.get('msg_type', ''))]

round2_data = {
    'round': 2,
    'focus': 'PDU Session Establishment flow',
    'full_timeline': raw_timeline,
    'sbi_errors': sbi_4xx,
    'pfcp_establishment_attempts': pfcp_establishment,
    'statistics': {
        'events_by_protocol': {},
        'sbi_status_distribution': {},
    }
}

# 简单统计
for ev in raw_timeline:
    proto = ev.get('protocol', 'Unknown')
    round2_data['statistics']['events_by_protocol'][proto] = round2_data['statistics']['events_by_protocol'].get(proto, 0) + 1

for c in raw_sbi:
    status = c.get('status', 'no_response')
    round2_data['statistics']['sbi_status_distribution'][str(status)] = round2_data['statistics']['sbi_status_distribution'].get(str(status), 0) + 1

user_prompt_r2 = f"""Round 2 Analysis

You now have more complete data:
{json.dumps(round2_data, indent=2, ensure_ascii=False)[:4000]}

Based on this comprehensive view:
1. Which of your Round 1 hypotheses are supported or refuted?
2. What is the most likely scenario now?
3. Identify the specific point where things go wrong (frame number, protocol, event)
4. What is your assessment: SUCCESS, FAILURE, or INCONCLUSIVE?

Provide analysis in JSON:
- hypothesis_evaluation: list of {{"hypothesis": "...", "verdict": "supported/refuted/uncertain", "reason": "..."}}
- most_likely_scenario: "description"
- breakdown_point: {{"where": "description", "frame": number or null}}
- verdict: "SUCCESS|FAILURE|INCONCLUSIVE"
- confidence: "high|medium|low"
- reasoning: "step by step thinking"""

print('\n  >> Calling LLM for Round 2 reasoning...')
resp_r2 = llm.complete(system_prompt, user_prompt_r2)
print('\n  >> LLM Round 2 Response:')
print('  ' + '-'*76)
lines_r2 = resp_r2.split('\n')
for line in lines_r2[:40]:
    print(f'  {line}')
if len(lines_r2) > 40:
    print(f'  ... ({len(lines_r2) - 40} more lines)')

# Round 3: 验证和总结
print('\n--- Round 3: 验证与总结 ---')
print('  Tool: frame_targeting + evidence_focus')

# 提取 LLM 认为的故障帧
breakdown_info = "Frame with repeated PDU Session Establishment attempts"

round3_data = {
    'round': 3,
    'task': 'verify diagnosis and provide recommendations',
    'target_frames': [
        {'frame': ev['frame'], 'event': ev.get('event'), 'protocol': ev.get('protocol')}
        for ev in raw_timeline
        if 'PDU' in str(ev.get('event', '')) or 'ESTABLISHMENT' in str(ev.get('event', ''))
    ],
    'suggested_root_causes': [
        'UPF connectivity issue (PFCP association failure)',
        'SMF configuration error',
        'Network resource exhaustion',
    ]
}

user_prompt_r3 = f"""Round 3 Final Analysis

Context: You previously identified a potential failure point.

Target frames to verify:
{json.dumps(round3_data, indent=2, ensure_ascii=False)[:2000]}

Final tasks:
1. Review the target frames - do they confirm your diagnosis?
2. Select the most likely root cause from the suggestions, or propose your own
3. Provide specific, actionable recommendations
4. Note any limitations or uncertainties in your analysis

Provide final diagnosis in JSON:
- verification: "do target frames confirm diagnosis? yes/no/partially"
- root_cause: "your conclusion"
- recommendations: ["actionable item 1", "actionable item 2"]
- limitations: ["what you're uncertain about", "what data is missing"]
- final_verdict: "SUCCESS|FAILURE|INCONCLUSIVE"
- final_confidence: "high|medium|low"""

print('\n  >> Calling LLM for Round 3 final analysis...')
resp_r3 = llm.complete(system_prompt, user_prompt_r3)
print('\n  >> LLM Round 3 Response:')
print('  ' + '-'*76)
lines_r3 = resp_r3.split('\n')
for line in lines_r3[:50]:
    print(f'  {line}')
if len(lines_r3) > 50:
    print(f'  ... ({len(lines_r3) - 50} more lines)')

# 总结
print('\n' + '='*80)
print('[5] Investigation 总结')
print('='*80)

print(f"""
调查完成！

对比分析：
----------------
传统规则驱动:
  - 信号: T3580_RETRY, PFCP_ASSOCIATION_RETRY（硬编码检测）
  - 假设: 复用 diagnosis.root_cause
  - 工具: 预定义行为
  - 结论: FAIL (PDU Session Establishment failed due to PFCP connectivity...)

开放式 LLM 驱动:
  - 信号: 无预定义，LLM 自己从原始数据发现
  - 假设: LLM 自主生成和验证
  - 工具: 返回原始数据，LLM 自己解释
  - 结论: 见 above LLM 输出

关键问题：
  1. LLM 能否正确识别 PDU Session Establishment 失败？
  2. LLM 能否定位到 PFCP/UPF 问题？
  3. LLM 的置信度是否与规则驱动一致？
""")

print('='*80)
print('实验完成')
print('='*80)
