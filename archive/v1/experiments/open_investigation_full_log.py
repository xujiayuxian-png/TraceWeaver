#!/usr/bin/env python3
"""
完整记录开放式 Investigation 的所有输入输出到文件
模型: ollama/qwen3.5:9b
"""

import json
from pathlib import Path
from datetime import datetime
from traceweaver.llm import LLMProvider, LLMConfig
from traceweaver.profiles.open5gs_5gc.extract.records import extract_records
from traceweaver.profiles.open5gs_5gc.assemble import group_ue_sessions, pair_sbi_calls, correlate_sbi_to_sessions

config = LLMConfig(model='ollama/qwen3.5:9b', max_retries=2)
llm = LLMProvider(config)
FIXTURES = Path('d:/code/TraceWeaver/tests/fixtures/pcap')

OUTPUT_FILE = Path('d:/code/TraceWeaver/investigation_full_io_log.txt')

test_file = FIXTURES / '07_pfcp_failure.pcapng'

# 准备输出缓冲区
output_lines = []
output_lines.append('='*100)
output_lines.append('开放式 Investigation 完整输入输出记录')
output_lines.append(f'时间: {datetime.now().isoformat()}')
output_lines.append(f'模型: ollama/qwen3.5:9b')
output_lines.append(f'测试文件: {test_file.name}')
output_lines.append('='*100)

# 数据准备
records = extract_records(test_file)
sessions = group_ue_sessions(records)
correlate_sbi_to_sessions(pair_sbi_calls(records), sessions)

session = None
for s in sessions:
    if s.pdu_sessions:
        session = s
        break
if not session:
    session = sessions[0] if sessions else None

# 辅助函数
def build_raw_timeline(session):
    lines = []
    for ev in session.events:
        info = {'frame': ev.frame_number, 'time': round(ev.time_epoch, 3), 'protocol': ev.protocol}
        if ev.event_name:
            info['event'] = ev.event_name
        if ev.cause is not None:
            info['cause'] = ev.cause
        if ev.pdu_session_id:
            info['pdu_id'] = ev.pdu_session_id
        lines.append(info)
    return lines

def build_sbi_raw(session):
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

pdu = session.pdu_sessions[0] if session.pdu_sessions else None
raw_timeline = build_raw_timeline(session)
raw_sbi = build_sbi_raw(session)
raw_pfcp = build_pfcp_raw(pdu) if pdu else []

# System Prompt（全局）
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

# ============ ROUND 1 ============
output_lines.append('\n' + '='*100)
output_lines.append('ROUND 1: 全局概览')
output_lines.append('='*100)

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

output_lines.append('\n--- SYSTEM PROMPT (全局) ---')
output_lines.append(system_prompt)
output_lines.append(f'\n--- ROUND 1 USER PROMPT ({len(user_prompt_r1)} chars) ---')
output_lines.append(user_prompt_r1)

print('Running Round 1...')
resp_r1 = llm.complete(system_prompt, user_prompt_r1)

output_lines.append(f'\n--- ROUND 1 LLM RESPONSE ({len(resp_r1)} chars) ---')
output_lines.append(resp_r1)

# ============ ROUND 2 ============
output_lines.append('\n' + '='*100)
output_lines.append('ROUND 2: 深度钻取')
output_lines.append('='*100)

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

output_lines.append(f'\n--- ROUND 2 USER PROMPT ({len(user_prompt_r2)} chars) ---')
output_lines.append(user_prompt_r2)

print('Running Round 2...')
resp_r2 = llm.complete(system_prompt, user_prompt_r2)

output_lines.append(f'\n--- ROUND 2 LLM RESPONSE ({len(resp_r2)} chars) ---')
output_lines.append(resp_r2)

# ============ ROUND 3 ============
output_lines.append('\n' + '='*100)
output_lines.append('ROUND 3: 验证与总结')
output_lines.append('='*100)

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

output_lines.append(f'\n--- ROUND 3 USER PROMPT ({len(user_prompt_r3)} chars) ---')
output_lines.append(user_prompt_r3)

print('Running Round 3...')
resp_r3 = llm.complete(system_prompt, user_prompt_r3)

output_lines.append(f'\n--- ROUND 3 LLM RESPONSE ({len(resp_r3)} chars) ---')
output_lines.append(resp_r3)

# 写入文件
output_lines.append('\n' + '='*100)
output_lines.append('END OF LOG')
output_lines.append('='*100)

with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
    f.write('\n'.join(output_lines))

print(f'\n完整记录已写入: {OUTPUT_FILE}')
print(f'总字符数: {sum(len(l) for l in output_lines)}')
