"""
End-to-end smoke for entry_points-based profile distribution.

Walks the full path a real third-party profile package would take:

    1. pip install -e tests/fixtures/external_profile_pkg/
    2. traceweaver profile list (must show tw_test_external)
    3. ProfileLoader().load("tw_test_external") via Python API
    4. pip uninstall (cleanup, even on failure)

This catches things unit tests can't: hatchling metadata, force-include
of profile.yaml, entry_points.txt actually being generated. Everything
that would only blow up "in production".

Usage::

    .venv\\Scripts\\python scripts/smoke_external_profile.py

Exits 0 on success, non-zero on any of the steps. Always tries to
uninstall the fixture before returning so subsequent runs are clean.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "external_profile_pkg"
DIST_NAME = "tw-test-external-profile"
PROFILE_NAME = "tw_test_external"


def _run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    print(f"[smoke] $ {' '.join(cmd)}")
    return subprocess.run(cmd, check=check, capture_output=True, text=True)


def _pip(*args: str) -> subprocess.CompletedProcess:
    return _run([sys.executable, "-m", "pip", *args], check=False)


def main() -> int:
    if not FIXTURE.is_dir():
        print(f"[smoke] FAIL: fixture missing at {FIXTURE}", file=sys.stderr)
        return 2

    rc = 0
    try:
        # ---- 1. install --------------------------------------------------
        out = _pip("install", "-e", str(FIXTURE), "--quiet")
        if out.returncode != 0:
            print("[smoke] FAIL: pip install errored", file=sys.stderr)
            print(out.stdout)
            print(out.stderr, file=sys.stderr)
            return 1

        # ---- 2. traceweaver profile list --------------------------------
        listed = _run(
            [sys.executable, "-m", "traceweaver.cli", "profile", "list",
             "--format", "json"],
            check=False,
        )
        # Note: traceweaver.cli has no __main__.py, so we route through
        # the package main() the same way scripts/smoke_mcp_serve.py does.
        if listed.returncode != 0:
            listed = _run(
                [sys.executable, "-c",
                 "from traceweaver.cli import main; "
                 "raise SystemExit(main(['profile','list','--format','json']))"],
                check=False,
            )
        if listed.returncode != 0:
            print("[smoke] FAIL: traceweaver profile list errored", file=sys.stderr)
            print(listed.stdout)
            print(listed.stderr, file=sys.stderr)
            return 1

        try:
            payload = json.loads(listed.stdout)
        except json.JSONDecodeError as exc:
            print(f"[smoke] FAIL: profile list output not JSON: {exc}", file=sys.stderr)
            print(listed.stdout)
            return 1

        by_name = {entry["name"]: entry for entry in payload}
        if PROFILE_NAME not in by_name:
            print(
                f"[smoke] FAIL: {PROFILE_NAME!r} not in `profile list`. "
                f"Got: {sorted(by_name)}",
                file=sys.stderr,
            )
            return 1
        entry = by_name[PROFILE_NAME]
        if entry["origin"] != "entry_point":
            print(
                f"[smoke] FAIL: expected origin=entry_point, got "
                f"{entry['origin']!r} (path={entry['path']})",
                file=sys.stderr,
            )
            return 1
        print(
            f"[smoke] OK: {PROFILE_NAME} discovered via entry_point "
            f"at {entry['path']}"
        )

        # ---- 3. ProfileLoader.load() Python API -------------------------
        load_check = _run(
            [sys.executable, "-c",
             "from traceweaver.core.profile import ProfileLoader; "
             f"p = ProfileLoader().load({PROFILE_NAME!r}); "
             f"print(p.name); "
             f"assert p.name == {PROFILE_NAME!r}"],
            check=False,
        )
        if load_check.returncode != 0:
            print("[smoke] FAIL: ProfileLoader.load() error", file=sys.stderr)
            print(load_check.stdout)
            print(load_check.stderr, file=sys.stderr)
            return 1
        print(f"[smoke] OK: ProfileLoader().load({PROFILE_NAME!r}) returned a Profile")
    except Exception as exc:  # pragma: no cover
        print(f"[smoke] FAIL: unexpected error: {exc}", file=sys.stderr)
        rc = 1
    finally:
        # ---- 4. cleanup -------------------------------------------------
        uninstall = _pip("uninstall", DIST_NAME, "-y", "--quiet")
        if uninstall.returncode != 0:
            print(
                "[smoke] WARN: pip uninstall returned non-zero; you may "
                "need to remove the fixture manually:",
                file=sys.stderr,
            )
            print(uninstall.stderr, file=sys.stderr)

    if rc == 0:
        print("[smoke] all checks passed")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
