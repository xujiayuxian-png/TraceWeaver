"""Internal helper: summarize / diff M3 regression baselines.

Usage:
    python scripts/_m3_compare.py scripts/m3_regression_baseline.json
    python scripts/_m3_compare.py a.json b.json  # side-by-side diff
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path


def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def _fmt_summary(report: dict, label: str) -> None:
    entries = report["entries"]
    verdicts = Counter((e.get("final_json") or {}).get("verdict") for e in entries)
    stops = Counter(e.get("stop_reason") for e in entries)
    rounds = [e.get("rounds_used", 0) for e in entries if e["ok"]]
    tools = [e.get("tool_calls_total", 0) for e in entries if e["ok"]]
    elapsed = [e.get("elapsed_s", 0) for e in entries if e["ok"]]
    tool_names = Counter()
    for e in entries:
        for c in e.get("calls") or []:
            tool_names[c] += 1

    print(f"=== {label} :: {report['model']} ===")
    print(f"  pcaps         : {len(entries)}")
    print(f"  total_elapsed : {report.get('elapsed_s')}s")
    print(f"  verdict mix   : {dict(verdicts)}")
    print(f"  stop_reason   : {dict(stops)}")
    if rounds:
        avg_r = sum(rounds) / len(rounds)
        avg_t = sum(tools) / len(tools)
        avg_e = sum(elapsed) / len(elapsed)
        print(f"  rounds  mn/avg/mx : {min(rounds)}/{avg_r:.1f}/{max(rounds)}")
        print(f"  tools   mn/avg/mx : {min(tools)}/{avg_t:.1f}/{max(tools)}")
        print(f"  elapsed mn/avg/mx : {min(elapsed):.1f}/{avg_e:.1f}/{max(elapsed):.1f}s")
    print("  tool calls (total):")
    for name, n in tool_names.most_common():
        print(f"    {name:30s} {n}")


def _fmt_per_pcap(report: dict) -> None:
    print()
    print(f"== per-pcap ({report['model']}) ==")
    for e in report["entries"]:
        fj = e.get("final_json") or {}
        v = fj.get("verdict") or "-"
        conf = fj.get("confidence", "-")
        stop = e.get("stop_reason", "-")
        print(
            f"  {e['pcap']:50s} {v:8s} stop={stop:22s} "
            f"conf={conf} rounds={e.get('rounds_used')} "
            f"tools={e.get('tool_calls_total')} {e.get('elapsed_s')}s"
        )


def _fmt_diff(a: dict, b: dict) -> None:
    a_map = {e["pcap"]: e for e in a["entries"]}
    b_map = {e["pcap"]: e for e in b["entries"]}
    common = sorted(set(a_map) & set(b_map))
    print()
    print(f"== diff {a['model']}  vs  {b['model']} ==")
    print(f"  {'pcap':50s} {'A.verdict':>10s}  {'B.verdict':>10s}  "
          f"{'A.stop':>22s}  {'B.stop':>22s}  {'A.rnd':>6s} {'B.rnd':>6s}  "
          f"{'A.s':>6s} {'B.s':>6s}")
    agree = 0
    for pcap in common:
        ea = a_map[pcap]
        eb = b_map[pcap]
        va = (ea.get("final_json") or {}).get("verdict") or "-"
        vb = (eb.get("final_json") or {}).get("verdict") or "-"
        if va == vb:
            agree += 1
        sa = ea.get("stop_reason") or "-"
        sb = eb.get("stop_reason") or "-"
        print(
            f"  {pcap:50s} {va:>10s}  {vb:>10s}  {sa:>22s}  {sb:>22s}  "
            f"{ea.get('rounds_used', '-'):>6}  {eb.get('rounds_used', '-'):>6}  "
            f"{ea.get('elapsed_s', '-'):>6}  {eb.get('elapsed_s', '-'):>6}"
        )
    print(f"  verdict agreement: {agree}/{len(common)}")


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        r = getattr(stream, "reconfigure", None)
        if r:
            try:
                r(encoding="utf-8", errors="replace")
            except Exception:
                pass

    if len(argv) == 1:
        a = _load(Path(argv[0]))
        _fmt_summary(a, "A")
        _fmt_per_pcap(a)
    elif len(argv) == 2:
        a = _load(Path(argv[0]))
        b = _load(Path(argv[1]))
        _fmt_summary(a, "A")
        _fmt_summary(b, "B")
        _fmt_diff(a, b)
    else:
        print("usage: _m3_compare.py REPORT.json [REPORT_B.json]")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
