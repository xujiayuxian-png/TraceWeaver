"""Quick tokens/s probe against an OpenAI-compatible endpoint.

Usage:
    python scripts/_ping_tokens.py --model qwen3.5-9b@q8_k_xl
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request


def ping(api_base: str, model: str, max_tokens: int) -> None:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": (
                    "Write a 200-word technical paragraph explaining "
                    "how HTTP/2 HPACK header compression works. "
                    "Be precise and concrete. No markdown."
                ),
            }
        ],
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "stream": False,
    }
    req = urllib.request.Request(
        f"{api_base.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer lm-studio",
        },
        method="POST",
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    dt = time.perf_counter() - t0

    usage = body.get("usage") or {}
    prompt_t = usage.get("prompt_tokens", 0)
    completion_t = usage.get("completion_tokens", 0)
    total_t = usage.get("total_tokens", 0)
    tps = completion_t / dt if dt else 0.0

    print(f"model:         {body.get('model')}")
    print(f"elapsed:       {dt:.2f}s")
    print(f"prompt tok:    {prompt_t}")
    print(f"completion tok:{completion_t}")
    print(f"total tok:     {total_t}")
    print(f"output tok/s:  {tps:.1f}")


def main(argv: list[str]) -> int:
    for s in (sys.stdout, sys.stderr):
        r = getattr(s, "reconfigure", None)
        if r:
            try:
                r(encoding="utf-8", errors="replace")
            except Exception:
                pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--api-base", default="http://127.0.0.1:1234/v1")
    ap.add_argument("--model", default="qwen3.5-9b@q8_k_xl")
    ap.add_argument("--max-tokens", type=int, default=200)
    args = ap.parse_args(argv)
    ping(args.api_base, args.model, args.max_tokens)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
