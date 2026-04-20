#!/usr/bin/env python3
"""Debug script to trace model loading/unloading."""
import requests
import time

base = "http://127.0.0.1:1234"

def check_models(label=""):
    print(f"\n=== {label} ===")
    resp = requests.get(f"{base}/api/v1/models")
    data = resp.json()
    loaded = []
    for m in data.get("models", []):
        for inst in m.get("loaded_instances", []):
            loaded.append({
                "key": m.get("key"),
                "instance_id": inst.get("id"),
                "config": inst.get("config", {})
            })
    print(f"Loaded models: {len(loaded)}")
    for l in loaded:
        print(f"  - key={l['key']}, instance={l['instance_id']}")
    return loaded

# Initial state
check_models("Initial state")

# Try loading qwen3.5-9b
print("\n>>> Loading qwen/qwen3.5-9b...")
resp = requests.post(
    f"{base}/api/v1/models/load",
    json={"model": "qwen/qwen3.5-9b", "context_length": 4096, "flash_attention": True},
    timeout=300
)
print(f"Load response: {resp.status_code}")
if resp.status_code == 200:
    print(f"Load result: {resp.json()}")
time.sleep(3)
check_models("After loading qwen3.5-9b")

# Try loading another model without unloading
print("\n>>> Loading qwen/qwen3-14b (without unloading)...")
resp = requests.post(
    f"{base}/api/v1/models/load",
    json={"model": "qwen/qwen3-14b", "context_length": 4096},
    timeout=300
)
print(f"Load response: {resp.status_code}")
time.sleep(3)
check_models("After loading qwen3-14b (both should be loaded)")

# Now unload all
print("\n>>> Unloading all instances...")
loaded = check_models("Before unload")
for l in loaded:
    inst_id = l["instance_id"]
    print(f"Unloading: {inst_id}")
    resp = requests.post(
        f"{base}/api/v1/models/unload",
        json={"instance_id": inst_id},
        timeout=30
    )
    print(f"  Response: {resp.status_code} - {resp.json()}")
    time.sleep(1)

time.sleep(2)
check_models("After unloading all")
