"""Compute accuracy of a regression report against two ground-truth sources:

1. Hard ground truth (`tests/fixtures/pcap` + smoke check functions) — the
   5 pcaps used by `run_m3_smoke.py`. Verdicts verified with the same
   check functions the smoke script uses.

2. Filename-inferred labels for the other 23 pcaps. These are *soft*
   ground truth, derived from the naming convention in
   `tests/fixtures/pcap`. A pcap called ``03_registration_reject`` is
   almost certainly a failure; ``13_pdu_session_release_clean`` is
   almost certainly a success. ``*_candidate``, ``*_manual``,
   ``partial_visibility``, ``truncated_or_lossy_capture`` are
   annotated as ``unclear`` to reflect genuine uncertainty.

Usage:
    python scripts/_m3_accuracy.py scripts/m3_regression_baseline.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from scripts.run_m3_smoke import build_tasks  # noqa: E402


# Filename-inferred soft ground-truth. ``accept`` is the set of
# verdicts we'd consider correct.
SOFT_LABELS: dict[str, set[str]] = {
    "01_registration_success.pcapng":                     {"success"},
    "02_registration_and_pdu_session_success.pcapng":     {"success"},
    "03_registration_reject.pcapng":                      {"failure"},
    "04_authentication_failure.pcapng":                   {"failure"},
    "05_pdu_session_reject.pcapng":                       {"failure"},
    "05_pdu_session_reject_clean.pcapng":                 {"failure"},
    "06_security_mode_reject_candidate.pcapng":           {"failure", "unclear"},
    "06_security_mode_reject_ia2_off_candidate.pcapng":   {"failure", "unclear"},
    "06_security_mode_reject_ia3_only_candidate.pcapng":  {"failure", "unclear"},
    "07_pfcp_failure.pcapng":                             {"failure"},
    "07_pfcp_failure_candidate.pcapng":                   {"failure", "unclear"},
    "07_pfcp_failure_long.pcapng":                        {"failure"},
    "07_pfcp_failure_retry.pcapng":                       {"failure"},
    "08_sbi_failure.pcapng":                              {"failure"},
    "08_sbi_failure_candidate.pcapng":                    {"failure", "unclear"},
    "08_sbi_failure_retry_ausf.pcapng":                   {"failure"},
    "08_sbi_failure_retry_udm.pcapng":                    {"failure"},
    "09_multi_ue_concurrent.pcapng":                      {"success"},
    "10_deregistration.pcapng":                           {"success"},
    "10_deregistration_cli.pcapng":                       {"success", "unclear"},
    "11_registration_retry.pcapng":                       {"failure", "unclear"},
    "12_service_request.pcapng":                          {"success", "unclear"},
    "12_service_request_candidate.pcapng":                {"success", "unclear"},
    "13_pdu_session_release.pcapng":                      {"success"},
    "13_pdu_session_release_clean.pcapng":                {"success"},
    "13_pdu_session_release_manual.pcapng":               {"unclear", "success"},
    "15_partial_visibility_multi_host.pcapng":            {"unclear", "success"},
    "16_truncated_or_lossy_capture.pcapng":               {"unclear", "failure"},
}


class _StubResult:
    """Adapter so we can reuse smoke's ``check`` callables directly."""

    def __init__(self, entry: dict) -> None:
        self.stop_reason = entry.get("stop_reason")
        self.final_json = entry.get("final_json") or {}
        calls = entry.get("calls") or []

        class _Call:
            def __init__(self, name: str) -> None:
                self.name = name

        class _Ex:
            def __init__(self, name: str) -> None:
                self.call = _Call(name)

        class _Ev:
            def __init__(self, names: list[str]) -> None:
                self.tool_executions = [_Ex(n) for n in names]

        class _Trace:
            def __init__(self, names: list[str]) -> None:
                self.events = [_Ev(names)]

        self.trace = _Trace(calls)


def evaluate(report_path: Path) -> None:
    for s in (sys.stdout, sys.stderr):
        r = getattr(s, "reconfigure", None)
        if r:
            try:
                r(encoding="utf-8", errors="replace")
            except Exception:
                pass

    rep = json.loads(report_path.read_text(encoding="utf-8"))
    entries = {e["pcap"]: e for e in rep["entries"]}
    tasks = {t.pcap: t for t in build_tasks()}

    print(f"=== accuracy :: {rep['model']} ===")
    print(f"    report: {report_path}")

    # --- hard ground-truth (smoke checks) ---
    print("\n-- hard ground-truth (smoke check functions, 5 pcaps) --")
    hard_ok = hard_total = 0
    for pcap, task in tasks.items():
        e = entries.get(pcap)
        if e is None:
            print(f"  {pcap:50s} MISSING (not in report)")
            continue
        hard_total += 1
        stub = _StubResult(e)
        ok, reason = task.check(stub)
        verdict = (e.get("final_json") or {}).get("verdict")
        status = "OK " if ok else "BAD"
        print(f"  [{status}] {pcap:50s} verdict={verdict!r:14s} :: {reason}")
        if ok:
            hard_ok += 1
    if hard_total:
        print(f"  hard accuracy: {hard_ok}/{hard_total} = {hard_ok/hard_total:.0%}")

    # --- soft ground-truth (filename-inferred) ---
    print("\n-- soft ground-truth (filename-inferred, all 28 pcaps) --")
    soft_ok = soft_bad = soft_miss = 0
    bads: list[str] = []
    for pcap, accept in SOFT_LABELS.items():
        e = entries.get(pcap)
        if e is None:
            soft_miss += 1
            continue
        v = (e.get("final_json") or {}).get("verdict")
        if v is None:
            soft_bad += 1
            bads.append(f"    {pcap:50s} NO_JSON (stop={e.get('stop_reason')})")
            continue
        if v in accept:
            soft_ok += 1
        else:
            soft_bad += 1
            bads.append(f"    {pcap:50s} got={v!r:10s} expected in {accept}")
    total = soft_ok + soft_bad
    if total:
        print(f"  soft accuracy: {soft_ok}/{total} = {soft_ok/total:.0%}")
        if bads:
            print("  misses:")
            for b in bads:
                print(b)


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: _m3_accuracy.py REPORT.json")
        return 2
    evaluate(Path(argv[0]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
