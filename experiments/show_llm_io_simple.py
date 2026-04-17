#!/usr/bin/env python3
"""简化版：展示LLM诊断的完整输入输出"""

from pathlib import Path
from traceweaver import analyze_capture
from traceweaver.llm import LLMProvider, LLMConfig
from traceweaver.llm.prompts import format_timeline, format_signals, SYSTEM_PROMPT, OUTPUT_SCHEMA
from traceweaver.core.profile import get_profile
from traceweaver.core.analysis.options import AnalysisOptions
from traceweaver.profiles.open5gs_5gc.extract.records import extract_records
from traceweaver.profiles.open5gs_5gc.assemble import group_ue_sessions, correlate_sbi_to_sessions, pair_sbi_calls, build_pdu_sessions_for_ue, correlate_pfcp_to_pdu

config = LLMConfig(model='ollama/qwen3.5:9b', max_retries=2)
llm = LLMProvider(config)
FIXTURES = Path('d:/code/TraceWeaver/tests/fixtures/pcap')

# 选择典型案例：注册拒绝
test_file = FIXTURES / '03_registration_reject.pcapng'

print('='*80)
print('LLM 诊断完整输入输出展示')
print(f'测试文件: {test_file.name}')
print(f'LLM模型: ollama/qwen3.5:9b')
print('='*80)

# 手动提取和组装
print('\n[1] 提取记录...')
records = extract_records(test_file)
print(f'    提取到 {len(records.records)} 条记录')

print('\n[2] 组装UE Session...')
warnings = list(records.warnings)
sessions = group_ue_sessions(records, warnings=warnings)
correlate_sbi_to_sessions(pair_sbi_calls(records), sessions, warnings=warnings)
for session in sessions:
    session.pdu_sessions = build_pdu_sessions_for_ue(session)
    correlate_pfcp_to_pdu(records, session.pdu_sessions, warnings=warnings)
    session.pdu_session_count = len(session.pdu_sessions)

print(f'    组装了 {len(sessions)} 个 UE Session')

# 获取第一个 session
session = sessions[0]
print(f'\n[3] 选择 Session: {session.session_id}')
print(f'    RAN-UE-NGAP-ID: {session.ran_ue_ngap_id}')
print(f'    AMF-UE-NGAP-ID: {session.amf_ue_ngap_id}')
print(f'    SUCI: {session.suci}')
print(f'    事件数: {session.event_count}')
print(f'    SBI调用数: {session.sbi_call_count}')

# 手动生成信号（使用 profile 的 _create_* 方法）
print('\n[4] 生成诊断信号...')
profile = get_profile('open5gs_5gc')

# 使用 profile 内部方法生成信号
signals = []

# 基础可见性信号
from traceweaver.profiles.open5gs_5gc.domain.diagnosis import DiagnosticSignal

if session.events:
    protocols = set(e.protocol for e in session.events)
    if 'NGAP' in protocols:
        signals.append(DiagnosticSignal(
            name='NGAP_VISIBLE', source='visibility',
            frame_number=session.events[0].frame_number,
            details={'protocol': 'NGAP', 'event_count': session.event_count}
        ))
    pfcp_flow_count = sum(len(p.pfcp_flows) for p in session.pdu_sessions) if session.pdu_sessions else 0
    if pfcp_flow_count > 0 or any('PFCP' in str(e.protocol) for e in session.events):
        signals.append(DiagnosticSignal(
            name='PFCP_VISIBLE', source='visibility',
            details={'protocol': 'PFCP'}
        ))
    if session.sbi_call_count > 0:
        signals.append(DiagnosticSignal(
            name='SBI_HTTP2_VISIBLE', source='visibility',
            details={'calls': session.sbi_call_count}
        ))

# 检查注册事件
core_events = [e.event_name for e in session.events]
if 'REGISTRATION_REQUEST' in core_events:
    idx = core_events.index('REGISTRATION_REQUEST')
    signals.append(DiagnosticSignal(
        name='REGISTRATION_REQUEST', source='nas',
        frame_number=session.events[idx].frame_number,
        details={}
    ))

if 'REGISTRATION_REJECT' in core_events:
    idx = core_events.index('REGISTRATION_REJECT')
    ev = session.events[idx]
    signals.append(DiagnosticSignal(
        name='REGISTRATION_REJECT', source='nas',
        frame_number=ev.frame_number,
        details={'cause': ev.cause}
    ))

if 'NGAP_UE_CONTEXT_RELEASE' in core_events:
    idx = core_events.index('NGAP_UE_CONTEXT_RELEASE')
    ev = session.events[idx]
    signals.append(DiagnosticSignal(
        name='NGAP_UE_CONTEXT_RELEASE', source='ngap',
        frame_number=ev.frame_number,
        details={'cause': ev.cause}
    ))

# SBI 4xx 检查
sbi_4xx_calls = [c for c in session.sbi_calls if c.status and 400 <= c.status < 500]
if sbi_4xx_calls:
    services_str = ','.join(set(c.service for c in sbi_4xx_calls))
    signals.append(DiagnosticSignal(
        name='SBI_4XX', source='sbi',
        frame_number=sbi_4xx_calls[0].request_frame,
        details={'count': len(sbi_4xx_calls), 'services': services_str}
    ))

print(f'    生成了 {len(signals)} 个信号')
for sig in signals:
    print(f'      - {sig.name} (frame {sig.frame_number or "N/A"})')

# 构建 Prompt
print('\n' + '='*80)
print('[5] LLM 完整输入')
print('='*80)

# 格式化 timeline
timeline_text = format_timeline(session)
signals_text = format_signals(signals)

# 构建 instruction (使用 large tier 的 instruction)
instruction = """\
Analyze the session timeline and signals above.
Determine whether this UE session succeeded or failed, identify the failure point and root cause if applicable.
Consider encrypted NAS messages (NGAP_INITIAL_CONTEXT_SETUP implies registration success even without visible REGISTRATION_ACCEPT)."""

user_prompt = f"""{timeline_text}

{signals_text}

{instruction}

{OUTPUT_SCHEMA}"""

print('\n>>> SYSTEM PROMPT (系统提示词):')
print('-'*80)
print(SYSTEM_PROMPT)
print('-'*80)

print('\n>>> USER PROMPT (用户提示词 - 完整):')
print('-'*80)
print(user_prompt)
print('-'*80)

# 计算 token 数（估算）
total_chars = len(SYSTEM_PROMPT) + len(user_prompt)
estimated_tokens = total_chars // 4
print(f'\n>>> Prompt 统计:')
print(f'    System prompt: {len(SYSTEM_PROMPT)} 字符')
print(f'    User prompt: {len(user_prompt)} 字符')
print(f'    总计: {total_chars} 字符 (约 {estimated_tokens} tokens)')

# 调用 LLM
print('\n' + '='*80)
print('[6] 调用 LLM...')
print('='*80)

response_text = llm.complete(SYSTEM_PROMPT, user_prompt)

print('\n>>> LLM 原始输出 (JSON):')
print('-'*80)
print(response_text)
print('-'*80)

# 解析结果
print('\n' + '='*80)
print('[7] 解析结果')
print('='*80)

import json
try:
    result = json.loads(response_text)
    print(f"    verdict: {result.get('verdict', 'N/A')}")
    print(f"    failure_point: {result.get('failure_point', 'N/A')}")
    print(f"    root_cause: {result.get('root_cause', 'N/A')}")
    print(f"    confidence: {result.get('confidence', 'N/A')}")
    print(f"    evidence items: {len(result.get('evidence', []))}")
    print(f"    suggestions: {result.get('suggestions', [])}")
    print(f"    limitations: {result.get('limitations', [])}")
    reasoning = result.get('reasoning', 'N/A')
    print(f"    reasoning: {reasoning[:300]}...")
except json.JSONDecodeError as e:
    print(f'    JSON解析错误: {e}')
    print(f'    原始输出前500字符: {response_text[:500]}')

print('\n' + '='*80)
print('展示完成')
print('='*80)
