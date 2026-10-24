#!/usr/bin/env python3
import sys
import json
import time
from pathlib import Path

sys.path.insert(0, '/root/stepfun-suite')
from src.oauth_login import poll_cli_login
from src.router_sync import submit_stepfun_key_to_9router

pending_file = Path('/tmp/pending_stepfun_login.json')
if not pending_file.exists():
    print("No pending login session found.")
    sys.exit(1)

data = json.loads(pending_file.read_text())
flow_id = data["flow_id"]
poll_token = data["poll_token"]
region = data["region"]

print(f"Starting background poll for flow_id={flow_id}...")
try:
    res = poll_cli_login(
        flow_id=flow_id,
        poll_token=poll_token,
        region=region,
        timeout_s=600,
        poll_interval_sec=2
    )
    api_key = res["api_key"]
    print("SUCCESS: Got API Key:", api_key)
    
    # Save to data/stepfun_keys.json
    out_dir = Path('/root/stepfun-suite/data')
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / 'stepfun_keys.json'
    records = []
    if out_file.exists():
        try:
            records = json.loads(out_file.read_text())
        except Exception:
            records = []
    records.append(res)
    out_file.write_text(json.dumps(records, indent=2))
    
    # Write to /tmp/latest_stepfun_key.txt for quick access
    Path('/tmp/latest_stepfun_key.txt').write_text(api_key.strip())
    
    # Sync to 9Router
    submit_stepfun_key_to_9router(api_key, name=f"StepFun Plan ({region})", region=region)
    print("Key synced to 9Router.")
except Exception as e:
    print("Poll worker error:", e)
    sys.exit(1)
