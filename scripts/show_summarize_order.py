"""Show if summarize_capture was called first or later for each task."""
import json
import sys
from pathlib import Path

path = Path(sys.argv[1] if len(sys.argv) > 1 else "reports/m3_smoke_dirA.json")
d = json.loads(path.read_text(encoding="utf-8"))

print(f"{'task':<32} {'ok':<5} {'summarize position':<20} calls")
for r in d["results"]:
    calls = r.get("calls") or []
    if "summarize_capture" in calls:
        pos = calls.index("summarize_capture") + 1
        pos_str = f"{pos}/{len(calls)}"
    else:
        pos_str = "NEVER"
    ok_str = str(r["ok"])
    print(f"  {r['task']:<30} {ok_str:<5} {pos_str:<20} {calls}")
