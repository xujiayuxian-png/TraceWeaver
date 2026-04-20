"""Quick helper: print telemetry summary from an M3-smoke JSON report."""
import json
import sys
from pathlib import Path

path = Path(sys.argv[1] if len(sys.argv) > 1 else "reports/m3_smoke_p1_verified.json")
d = json.loads(path.read_text(encoding="utf-8"))
print(f"Report: {path}")
print(f"Model:  {d['model']}")
print(f"Passed: {d['passed']}/{d['total']}")
print(f"Total tokens:     {d['total_tokens']}")
print(f"Total cost (USD): {d['total_cost_usd']}")
print(f"Total wall clock: {d['total_wall_clock_s']}s")
print()
print("Per-task telemetry:")
print(f"  {'task':<32} {'ok':<5} {'tokens':>8} {'wall_s':>8} rounds tools")
for r in d["results"]:
    print(
        f"  {r['task']:<32} {str(r['ok']):<5} "
        f"{r.get('total_tokens') or '-':>8} "
        f"{r.get('wall_clock_s') or '-':>8} "
        f"{r.get('rounds_used'):>6} {r.get('tool_calls_total'):>5}"
    )
