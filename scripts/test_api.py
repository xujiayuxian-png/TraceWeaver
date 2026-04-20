#!/usr/bin/env python3
"""Quick test of LM Studio v1 API."""
import requests
import time

base = "http://127.0.0.1:1234"

# Check current loaded model
print("=== Checking loaded model ===")
resp = requests.get(f"{base}/api/v1/models")
data = resp.json()
loaded = [m for m in data["models"] if m.get("loaded_instances")]
print(f"Loaded: {[m['key'] for m in loaded]}")

# Unload current
if loaded:
    key = loaded[0]["key"]
    print(f"\n=== Unloading {key} ===")
    resp = requests.post(f"{base}/api/v1/models/unload", json={"instance_id": key})
    print(f"Unload status: {resp.status_code}")
    time.sleep(2)

# Load a different model
print("\n=== Loading qwen3-14b ===")
resp = requests.post(
    f"{base}/api/v1/models/load",
    json={"model": "qwen/qwen3-14b", "context_length": 4096, "flash_attention": True},
    timeout=300
)
print(f"Load status: {resp.status_code}")
if resp.status_code == 200:
    result = resp.json()
    print(f"Loaded in {result.get('load_time_seconds', '?')}s")
    time.sleep(3)
    # Check again
    resp2 = requests.get(f"{base}/api/v1/models")
    loaded2 = [m["key"] for m in resp2.json()["models"] if m.get("loaded_instances")]
    print(f"Now loaded: {loaded2}")
else:
    print(f"Error: {resp.text}")
