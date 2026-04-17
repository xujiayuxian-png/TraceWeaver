#!/usr/bin/env python3
"""展示 Investigation 的完整循环和 Tool Call 过程"""

from pathlib import Path
from traceweaver import investigate_capture
from traceweaver.llm import LLMProvider, LLMConfig

config = LLMConfig(model='ollama/qwen3.5:9b', max_retries=2)
llm = LLMProvider(config)
FIXTURES = Path('d:/code/TraceWeaver/tests/fixtures/pcap')

# 选择一个复杂案例：PFCP 失败
test_file = FIXTURES / '07_pfcp_failure.pcapng'

print('='*80)
print('Investigation 完整流程展示')
print(f'测试文件: {test_file.name}')
print(f'LLM模型: ollama/qwen3.5:9b')
print('='*80)

print('\n开始调查...')
print()

result = investigate_capture(test_file, llm_provider=llm, scope_id=None)

print(f'调查文件: {result.file_name}')
print(f'Profile: {result.profile_name}')
print(f'调查Scope数: {result.scope_count}')
print(f'总体判决: {result.overall_verdict}')
print(f'失败点: {result.overall_failure_point or "N/A"}')
print(f'置信度: {result.overall_confidence}')
print()

# 展示每个 scope 的调查详情
for inv in result.investigations:
    print(f'='*80)
    print(f'Scope 调查详情: {inv.scope_id}')
    print(f'='*80)
    print(f'  Scope类型: {inv.scope_type}')
    print(f'  最终判决: {inv.verdict}')
    print(f'  置信度: {inv.confidence}')
    print(f'  调查轮数: {inv.round_count}')
    print(f'  执行工具: {inv.executed_tools}')
    print(f'  假设列表: {inv.hypotheses}')
    print()
    
    if inv.plan:
        print(f'  初始计划:')
        print(f'    工具序列: {inv.plan.tool_sequence}')
        print(f'    假设数量: {len(inv.plan.hypotheses)}')
        for i, h in enumerate(inv.plan.hypotheses, 1):
            print(f'    [{i}] {h.statement}')
        print()
    
    print(f'  详细步骤 ({len(inv.steps)}步):')
    for i, step in enumerate(inv.steps, 1):
        print(f'    Step {i}: {step.action} | {step.status}')
        print(f'      摘要: {step.summary}')
        if step.details:
            # 选择性展示关键字段
            if 'round_index' in step.details:
                print(f'      轮次: {step.details["round_index"]}')
            if 'tool_name' in step.details:
                print(f'      工具: {step.details["tool_name"]}')
            if 'hypothesis' in step.details and step.details['hypothesis']:
                print(f'      假设: {step.details["hypothesis"][:60]}...')
            if 'result' in step.details and isinstance(step.details['result'], dict):
                result_summary = step.details['result'].get('summary', '')
                if result_summary:
                    print(f'      结果: {result_summary}')
        print()
    
    if inv.termination:
        print(f'  终止条件:')
        print(f'    状态: {inv.termination.status}')
        print(f'    原因: {inv.termination.reason}')
        print(f'    建议: {inv.termination.suggested_next}')
        print()
    
    if inv.tool_results:
        print(f'  工具执行结果 ({len(inv.tool_results)}个):')
        for tr in inv.tool_results:
            print(f'    - {tr.tool_name}: {tr.summary}')
            if tr.evidence_refs:
                print(f'      关联证据: {tr.evidence_refs}')
        print()

print('='*80)
print('调查完成')
print('='*80)
