#!/usr/bin/env python3
"""测试核心抓包文件"""

import sys
from pathlib import Path
from traceweaver import analyze_capture
from traceweaver.llm import LLMProvider, LLMConfig

config = LLMConfig(model='ollama/qwen3.5:9b', max_retries=2)
llm = LLMProvider(config)
FIXTURES = Path('d:/code/TraceWeaver/tests/fixtures/pcap')

# 核心测试文件
pcaps = [
    '01_registration_success.pcapng',
    '02_registration_and_pdu_session_success.pcapng',
    '03_registration_reject.pcapng',
    '04_authentication_failure.pcapng',
    '05_pdu_session_reject.pcapng',
    '07_pfcp_failure.pcapng',
    '08_sbi_failure.pcapng',
    '09_multi_ue_concurrent.pcapng',
]

print('='*80)
print('测试核心抓包文件 (ollama/qwen3.5:9b)')
print('='*80)

results = []

for i, pcap_name in enumerate(pcaps, 1):
    pcap = FIXTURES / pcap_name
    if not pcap.exists():
        print(f'[{i}/{len(pcaps)}] {pcap_name} - 文件不存在，跳过')
        continue
        
    print()
    print(f'[{i}/{len(pcaps)}] {pcap_name}')
    print('-'*80)
    
    try:
        result = analyze_capture(pcap, llm_provider=llm)
        
        fp = result.overall_failure_point or 'N/A'
        rc = result.overall_root_cause or 'N/A'
        
        print(f'  判决: {result.overall_verdict}')
        print(f'  失败点: {fp}')
        print(f'  根因: {rc[:80]}...' if len(rc) > 80 else f'  根因: {rc}')
        print(f'  置信度: {result.overall_confidence}')
        print(f'  Scopes: {result.scope_count}')
        
        engine_info = 'N/A'
        for w in result.warnings:
            if 'engine' in w:
                engine_info = w
                print(f'  引擎: {w}')
                break
                
        if result.diagnoses:
            print(f'  详细诊断:')
            for d in result.diagnoses:
                d_fp = d.failure_point or 'N/A'
                print(f'    - {d.scope_id}: {d.verdict} | {d_fp} | {d.confidence}')
                if d.root_cause:
                    short_rc = d.root_cause[:60] + '...' if len(d.root_cause) > 60 else d.root_cause
                    print(f'      根因: {short_rc}')
                    
        results.append({
            'file': pcap_name,
            'verdict': result.overall_verdict,
            'failure_point': fp,
            'confidence': result.overall_confidence,
            'scopes': result.scope_count,
            'engine': engine_info,
        })
                    
    except Exception as e:
        error_msg = f'{type(e).__name__}: {e}'
        print(f'  错误: {error_msg}')
        import traceback
        traceback.print_exc()
        results.append({
            'file': pcap_name,
            'verdict': 'ERROR',
            'failure_point': error_msg,
            'confidence': 'low',
            'scopes': 0,
            'engine': 'N/A',
        })

print()
print('='*80)
print('测试汇总')
print('='*80)
print()
print(f'{"文件名":<50} {"判决":<12} {"失败点":<25} {"置信度":<8} {"引擎"}')
print('-'*120)
for r in results:
    print(f'{r["file"]:<50} {r["verdict"]:<12} {r["failure_point"]:<25} {r["confidence"]:<8} {r["engine"]}')

print()
print('='*80)
print('测试完成')
print('='*80)
