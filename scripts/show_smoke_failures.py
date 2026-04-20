"""Dump failure details from a smoke report for diagnosis."""
import json
import sys
from pathlib import Path

path = Path(sys.argv[1] if len(sys.argv) > 1 else "reports/m3_smoke_p1_verified.json")
d = json.loads(path.read_text(encoding="utf-8"))

fails = [r for r in d["results"] if not r["ok"]]
print(f"=== {len(fails)} failures ===\n")

for r in fails:
    print(f"--- {r['task']} ---")
    print(f"  pcap:       {r['pcap']}")
    print(f"  description: {r['description']}")
    print(f"  reason:     {r['reason']}")
    print(f"  rounds:     {r.get('rounds_used')}")
    print(f"  tool_calls: {r.get('calls')}")
    print(f"  tokens:     {r.get('total_tokens')}")
    print(f"  wall_s:     {r.get('wall_clock_s')}")
    fj = r.get("final_json") or {}
    print(f"  verdict:    {fj.get('verdict')}")
    print(f"  summary:    {(fj.get('summary') or '')[:200]}")
    rc = fj.get("root_cause")
    if rc:
        print(f"  root_cause: {rc[:200]}")
    fp = fj.get("failure_point")
    if fp:
        print(f"  fail_point: {str(fp)[:200]}")
    ev = fj.get("evidence") or []
    print(f"  evidence ({len(ev)} items):")
    for i, e in enumerate(ev[:5]):
        print(f"    [{i}] seq={e.get('seq')} event={e.get('event')} note={(e.get('note') or '')[:120]}")
    print(f"  confidence: {fj.get('confidence')}")
    print()
