#!/usr/bin/env python3
"""展示LLM诊断的完整输入输出"""

from pathlib import Path
from traceweaver import analyze_capture
from traceweaver.llm import LLMProvider, LLMConfig
from traceweaver.llm.prompts import format_timeline, format_signals, build_diagnosis_prompt, SYSTEM_PROMPT, OUTPUT_SCHEMA
from traceweaver.core.profile import get_profile
from traceweaver.core.analysis.options import AnalysisOptions

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

# 先获取分析结果和运行时数据
profile_impl = get_profile('open5gs_5gc')
options = AnalysisOptions()

# 手动调用 profile 的 extract 和 build_scopes 获取 session
from traceweaver.profiles.open5gs_5gc.extract.records import extract_records
from traceweaver.profiles.open5gs_5gc.assemble import group_ue_sessions, correlate_sbi_to_sessions, pair_sbi_calls, build_pdu_sessions_for_ue, correlate_pfcp_to_pdu

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

# 获取第一个 session 的信号
session = sessions[0]
print(f'\n[3] 选择 Session: {session.session_id}')
print(f'    RAN-UE-NGAP-ID: {session.ran_ue_ngap_id}')
print(f'    AMF-UE-NGAP-ID: {session.amf_ue_ngap_id}')
print(f'    SUCI: {session.suci}')
print(f'    事件数: {session.event_count}')
print(f'    SBI调用数: {session.sbi_call_count}')

# 使用 profile 生成信号
print('\n[4] 生成诊断信号...')
from traceweaver.profiles.open5gs_5gc.runtime import Open5GSAnalysisRuntime
runtime = Open5GSAnalysisRuntime(
    record_set=records,
    warnings=warnings,
    sessions=sessions,
    signal_cache={},
)
from traceweaver.core.contracts import AnalysisScope
scope = AnalysisScope(
    scope_id=session.session_id,
    scope_type="ue_session",
    display_name=f"UE {session.suci or session.supi or 'unknown'}",
    records=[r for r in records.records if getattr(r, 'ran_ue_ngap_id', None) == session.ran_ue_ngap_id or getattr(r, 'amf_ue_ngap_id', None) == session.amf_ue_ngap_id],
    events=session.events,
    children=[],
)
profile_impl.annotate_signals(scope, runtime)
signals = runtime.signal_cache.get(session.session_id, [])
print(f'    生成了 {len(signals)} 个信号')
for sig in signals:
    print(f'      - {sig.name} (frame {sig.frame_number or "N/A"})')

# 构建 Prompt
print('\n' + '='*80)
print('[5] LLM 完整输入')
print('='*80)

# 构建 system prompt 和 user prompt
from traceweaver.profiles.open5gs_5gc.domain.diagnosis import DiagnosticSignal

# 手动格式化
timeline_text = format_timeline(session)
signals_text = format_signals(signals)

# 构建完整的 user prompt (参考 prompts.py 中的 _build_large_instruction)
instruction = """\
Analyze the session timeline and signals above.
Determine whether this UE session succeeded or failed, identify the failure point and root cause if applicable.
Consider encrypted NAS messages (NGAP_INITIAL_CONTEXT_SETUP implies registration success even without visible REGISTRATION_ACCEPT)."""

user_prompt = f"""{timeline_text}

{signals_text}

{instruction}

{OUTPUT_SCHEMA}"""

print('\n>>> SYSTEM PROMPT (前500字符):')
print(SYSTEM_PROMPT[:500] + '...')

print('\n>>> USER PROMPT (完整):')
print('-'*80)
print(user_prompt)
print('-'*80)

# 计算 token 数（估算）
total_chars = len(SYSTEM_PROMPT) + len(user_prompt)
estimated_tokens = total_chars // 4  # 粗略估算
print(f'\n>>> Prompt 统计:')
print(f'    System prompt: {len(SYSTEM_PROMPT)} 字符')
print(f'    User prompt: {len(user_prompt)} 字符')
print(f'    总计: {total_chars} 字符 (约 {estimated_tokens} tokens)')

# 调用 LLM
print('\n' + '='*80)
print('[6] 调用 LLM...')
print('='*80)

# 构建完整 prompt
full_prompt = f"{SYSTEM_PROMPT}\n\n{user_prompt}"

response_text = llm.complete(full_prompt)

print('\n>>> LLM 原始输出 (JSON):')
print('-'*80)
print(response_text[:3000] if len(response_text) > 3000 else response_text)
if len(response_text) > 3000:
    print(f'... (输出被截断，完整长度: {len(response_text)} 字符)')
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
    print(f"    reasoning: {result.get('reasoning', 'N/A')[:200]}...")
except json.JSONDecodeError as e:
    print(f'    JSON解析错误: {e}')
    print(f'    原始输出前500字符: {response_text[:500]}')

print('\n' + '='*80)
print('展示完成')
print('='*80)
