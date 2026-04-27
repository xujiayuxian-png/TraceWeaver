"""
Allow `python -m traceweaver.cli ...` as an alternative to the
`traceweaver` console script. Useful in environments where the
console script isn't on PATH (e.g. some CI runners, smoke tests).
"""

from traceweaver.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
