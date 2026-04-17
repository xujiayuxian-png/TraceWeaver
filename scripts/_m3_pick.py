"""Print one entry from a regression report (just the final_json + calls)."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv):
    for s in (sys.stdout, sys.stderr):
        r = getattr(s, "reconfigure", None)
        if r:
            try:
                r(encoding="utf-8", errors="replace")
            except Exception:
                pass

    if len(argv) != 2:
        print("usage: _m3_pick.py REPORT.json PCAPNAME")
        return 2
    rep = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    for e in rep["entries"]:
        if e["pcap"] == argv[1]:
            print(f"== {rep['model']} :: {e['pcap']} ==")
            print(f"   stop={e.get('stop_reason')} rounds={e.get('rounds_used')} "
                  f"tools={e.get('tool_calls_total')} elapsed={e.get('elapsed_s')}s")
            print(f"   calls: {e.get('calls')}")
            fj = e.get("final_json")
            print("   final_json:")
            print(json.dumps(fj, ensure_ascii=False, indent=2))
            return 0
    print(f"pcap not found: {argv[1]}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
