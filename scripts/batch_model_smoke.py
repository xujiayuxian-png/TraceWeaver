"""
Batch test all LM Studio models with M3 smoke tests.
Automatically loads each model via API, runs smoke test, unloads, moves to next.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import requests

LMSTUDIO_BASE = "http://127.0.0.1:1234"
SMOKE_SCRIPT = Path(__file__).parent / "run_m3_smoke.py"

# Models to test: (lmstudio_key, litellm_model_id, display_name)
# IMPORTANT: litellm_model_id must be "openai/<full_lmstudio_key>" to prevent
# LM Studio from JIT-loading a different variant (e.g. q4_k_m when we loaded Q8).
MODELS = [
    ("qwen/qwen3.5-9b", "openai/qwen/qwen3.5-9b", "Qwen3.5-9B-Q8"),
    ("qwen/qwen3-14b", "openai/qwen/qwen3-14b", "Qwen3-14B"),
    ("openai/gpt-oss-20b", "openai/openai/gpt-oss-20b", "GPT-OSS-20B"),
    ("google/gemma-4-26b-a4b", "openai/google/gemma-4-26b-a4b", "Gemma-4-26B-A4B"),
    ("google/gemma-4-e4b", "openai/google/gemma-4-e4b", "Gemma-4-E4B"),
    ("qwen3.5-9b@q5_k_m", "openai/qwen3.5-9b@q5_k_m", "Qwen3.5-9B-Q5KM"),
    ("qwen3.5-9b@q8_k_xl", "openai/qwen3.5-9b@q8_k_xl", "Qwen3.5-9B-Q8XL"),
    ("zai-org/glm-4.7-flash", "openai/zai-org/glm-4.7-flash", "GLM-4.7-Flash"),
]


def get_loaded_model_key() -> str | None:
    """Get the key of currently loaded model."""
    try:
        resp = requests.get(f"{LMSTUDIO_BASE}/api/v1/models", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            for m in data.get("models", []):
                if m.get("loaded_instances"):
                    return m.get("key")
        return None
    except Exception as e:
        print(f"  [check] warning: {e}")
        return None


def get_all_loaded_instances() -> list[str]:
    """Get all loaded model instance IDs."""
    try:
        resp = requests.get(f"{LMSTUDIO_BASE}/api/v1/models", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            instances = []
            for m in data.get("models", []):
                for inst in m.get("loaded_instances", []):
                    instances.append(inst.get("id"))
            return instances
        return []
    except Exception as e:
        print(f"  [check] warning: {e}")
        return []


def unload_all_models() -> bool:
    """Unload ALL loaded model instances using v1 API."""
    instances = get_all_loaded_instances()
    if not instances:
        print("  [unload] no models loaded")
        return True
    
    success = True
    for inst_id in instances:
        try:
            resp = requests.post(
                f"{LMSTUDIO_BASE}/api/v1/models/unload",
                json={"instance_id": inst_id},
                timeout=30
            )
            if resp.status_code == 200:
                print(f"  [unload] success: {inst_id}")
            else:
                print(f"  [unload] failed {inst_id}: {resp.status_code}")
                success = False
        except Exception as e:
            print(f"  [unload] error {inst_id}: {e}")
            success = False
    return success


def load_model(model_key: str) -> bool:
    """Load a model by key using v1 API."""
    try:
        resp = requests.post(
            f"{LMSTUDIO_BASE}/api/v1/models/load",
            json={
                "model": model_key,
                "context_length": 8192,
                "flash_attention": True
            },
            timeout=300  # Loading can take a while
        )
        if resp.status_code == 200:
            result = resp.json()
            print(f"  [load] loaded in {result.get('load_time_seconds', '?')}s")
            # Wait a bit for model to be fully ready
            for i in range(10):
                time.sleep(1)
                loaded = get_loaded_model_key()
                if loaded == model_key:
                    return True
            return False
        else:
            print(f"  [load] failed: {resp.status_code} - {resp.text}")
            return False
    except Exception as e:
        print(f"  [load] error: {e}")
        return False


def run_smoke(model_id: str, report_dir: Path) -> dict[str, Any]:
    """Run M3 smoke test for a model."""
    safe_name = model_id.replace("/", "_").replace("@", "_")
    report_path = report_dir / f"m3_smoke_{safe_name}.json"
    
    # Copy full environment and add tshark path
    env = dict(subprocess.os.environ)
    env["PATH"] = "C:/Program Files/Wireshark;" + env.get("PATH", "")
    
    start = time.time()
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(SMOKE_SCRIPT),
                "--model", model_id,
                "--api-base", f"{LMSTUDIO_BASE}/v1",
                "--report", str(report_path),
            ],
            capture_output=True,
            text=True,
            timeout=600,
            env=env,
        )
        elapsed = time.time() - start
        
        # Parse results
        passed = 0
        total = 9
        for line in result.stdout.split("\n"):
            if "tasks passed" in line:
                try:
                    passed = int(line.split("/")[0].split()[-1])
                except:
                    pass
        
        return {
            "model": model_id,
            "passed": passed,
            "total": total,
            "elapsed_s": round(elapsed, 1),
            "report": str(report_path) if report_path.exists() else None,
            "stdout": result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout,
            "stderr": result.stderr[-500:] if result.stderr else "",
            "exit_code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"model": model_id, "error": "timeout", "elapsed_s": 600}
    except Exception as e:
        return {"model": model_id, "error": str(e), "elapsed_s": time.time() - start}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="Test only this model ID")
    ap.add_argument("--report-dir", type=Path, default=Path("reports/batch_smoke"))
    args = ap.parse_args()
    
    args.report_dir.mkdir(parents=True, exist_ok=True)
    
    models = MODELS
    if args.only:
        models = [m for m in MODELS if args.only in m[0] or args.only in m[1]]
    
    # Force cleanup at start
    print("[Batch Smoke] Force unloading any existing models...")
    unload_all_models()
    time.sleep(3)
    
    print(f"[Batch Smoke] Testing {len(models)} models")
    print(f"[Batch Smoke] Reports: {args.report_dir}")
    print()
    
    results = []
    for idx, (load_id, call_id, name) in enumerate(models, 1):
        print(f"[{idx}/{len(models)}] {name}")
        print(f"  load_id: {load_id}")
        print(f"  call_id: {call_id}")
        
        # Unload previous - double check
        print("  -> Unloading previous model...")
        unload_all_models()
        time.sleep(3)  # Wait longer for VRAM release
        
        # Load new model
        print("  -> Loading model...")
        if not load_model(load_id):
            print("  -> FAILED to load, skipping")
            results.append({"model": call_id, "error": "load failed"})
            continue
        print("  -> Model loaded, running smoke test...")
        
        # Run smoke test
        result = run_smoke(call_id, args.report_dir)
        results.append(result)
        
        status = f"{result.get('passed', '?' )}/{result.get('total', 9)}"
        print(f"  -> Result: {status} in {result.get('elapsed_s', '?')}s")
        print()
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    for r in results:
        model = r["model"].split("/")[-1][:30]
        if "error" in r:
            print(f"  {model:30} ERROR: {r['error']}")
        else:
            print(f"  {model:30} {r.get('passed', '?')}/{r.get('total', 9)} ({r.get('elapsed_s', '?')}s)")
    
    # Save summary
    summary_path = args.report_dir / "batch_summary.json"
    summary_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"\nSummary saved to: {summary_path}")


if __name__ == "__main__":
    main()
