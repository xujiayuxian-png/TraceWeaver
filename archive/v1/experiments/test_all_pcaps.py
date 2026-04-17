#!/usr/bin/env python3
"""测试所有pcap文件的完整流程"""

import sys
from pathlib import Path
from traceweaver import analyze_capture
from traceweaver.llm import LLMProvider, LLMConfig

config = LLMConfig(model='ollama/qwen3.5:9b', max_retries=2)
llm = LLMProvider(config)
FIXTURES = Path('d:/code/TraceWeaver/tests/fixtures/pcap')

# 获取所有pcap文件
pcaps = sorted([f for f in FIXTURES.glob('*.pcapng')])

print('='*80)
print('开始测试所有抓包文件')
print(f'总计: {len(pcaps)} 个文件')
print('='*80)

results_summary = []

for i, pcap in enumerate(pcaps, 1):
    print()
    print(f'[{i}/{len(pcaps)}] 测试文件: {pcap.name}')
    print('-'*80)
    
    try:
        result = analyze_capture(pcap, llm_provider=llm)
        
        print(f'  路径: {result.path}')
        print(f'  文件名: {result.file_name}')
        print(f'  Profile: {result.profile_name}')
        print(f'  Scope数量: {result.scope_count}')
        print()
        print(f'  总体判决: {result.overall_verdict}')
        print(f'  失败点: {result.overall_failure_point or "N/A"}')
        print(f'  根因: {result.overall_root_cause or "N/A"}')
        print(f'  置信度: {result.overall_confidence}')
        print()
        
        if result.warnings:
            print(f'  警告 ({len(result.warnings)}个):')
            for w in result.warnings:
                print(f'    - {w}')
            print()
        
        if result.diagnoses:
            print(f'  详细诊断 ({len(result.diagnoses)}个scope):')
            for j, d in enumerate(result.diagnoses, 1):
                print(f'    [{j}] Scope: {d.scope_id}')
                print(f'         判决: {d.verdict}')
                print(f'         失败点: {d.failure_point or "N/A"}')
                print(f'         根因: {d.root_cause or "N/A"}')
                print(f'         置信度: {d.confidence}')
                print(f'         信号数: {len(d.signal_names)}')
                if d.signal_names:
                    signals_str = str(d.signal_names[:10])
                    if len(d.signal_names) > 10:
                        signals_str += f' ... (共{len(d.signal_names)}个)'
                    print(f'         信号: {signals_str}')
                if d.notes:
                    print(f'         备注 ({len(d.notes)}个):')
                    for n in d.notes[:3]:
                        print(f'           - {n}')
                    if len(d.notes) > 3:
                        print(f'           ... 还有 {len(d.notes)-3} 条')
                print()
        
        if result.scopes:
            print(f'  Scope详情 ({len(result.scopes)}个):')
            for s in result.scopes:
                print(f'    - {s.scope_id} ({s.scope_type}): {s.display_name}')
                print(f'      记录数: {len(s.records)}, 事件数: {len(s.events)}, 子scope: {len(s.children)}')
            print()
        
        results_summary.append({
            'file': pcap.name,
            'verdict': result.overall_verdict,
            'failure_point': result.overall_failure_point,
            'confidence': result.overall_confidence,
            'scopes': result.scope_count,
            'status': 'OK'
        })
            
    except Exception as e:
        error_msg = f'{type(e).__name__}: {e}'
        print(f'  错误: {error_msg}')
        import traceback
        traceback.print_exc()
        results_summary.append({
            'file': pcap.name,
            'verdict': 'ERROR',
            'failure_point': None,
            'confidence': 'low',
            'scopes': 0,
            'status': error_msg
        })
    
    print(f'[{i}/{len(pcaps)}] {pcap.name} 完成')

print()
print('='*80)
print('测试汇总')
print('='*80)
print()
print(f'{"文件名":<50} {"判决":<12} {"失败点":<25} {"置信度":<8} {"Scopes"}')
print('-'*120)
for r in results_summary:
    fp = r['failure_point'] or 'N/A'
    print(f'{r["file"]:<50} {r["verdict"]:<12} {fp:<25} {r["confidence"]:<8} {r["scopes"]}')

print()
print('='*80)
print('所有测试完成')
print('='*80)
