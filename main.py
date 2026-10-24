#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
StepFun Suite — Entry Point CLI.
Automates StepFun Step Plan authentication, smoke testing, and 9Router gateway synchronization.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from src.oauth_login import start_cli_login, poll_cli_login, REGIONS
from src.client import StepFunClient
from src.router_sync import submit_stepfun_key_to_9router

# ANSI Color definitions
G = "\033[92m"
R = "\033[91m"
Y = "\033[93m"
C = "\033[96m"
M = "\033[95m"
W = "\033[97m"
B = "\033[1m"
DIM = "\033[2m"
X = "\033[0m"

logging.basicConfig(level=logging.INFO, format=f"{DIM}%(asctime)s{X} [%(levelname)s] %(message)s")
logger = logging.getLogger("StepFunSuite")


def save_key_record(record: dict) -> Path:
    data_dir = BASE_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    out_file = data_dir / "stepfun_keys.json"
    existing = []
    if out_file.exists():
        try:
            existing = json.loads(out_file.read_text(encoding="utf-8"))
        except Exception:
            existing = []

    # Update or append
    updated = False
    for i, item in enumerate(existing):
        if item.get("api_key") == record.get("api_key"):
            existing[i] = record
            updated = True
            break
    if not updated:
        existing.append(record)

    out_file.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    os.chmod(out_file, 0o600)
    return out_file


def cmd_login(args: argparse.Namespace) -> None:
    print(f"\n{C}{'═' * 64}{X}")
    print(f" {B}{C}  ⚡ STEPFUN STEP PLAN — OUTBOUND CLI LOGIN ⚡{X}")
    print(f"{C}{'═' * 64}{X}")
    print(f"  {DIM}Region  :{X} {Y}{B}{args.region}{X}")
    print(f"  {DIM}Target  :{X} {W}{REGIONS[args.region]['origin']}{X}")
    print(f"{C}{'─' * 64}{X}\n")

    init_res = start_cli_login(region=args.region, proxy=args.proxy)
    flow_id = init_res["flow_id"]
    auth_url = init_res["authorize_url"]
    poll_token = init_res["poll_token"]

    print(f"{Y}{B}[ACTION REQUIRED]{X} Buka URL berikut di browser kamu untuk approve login:")
    print(f"\n  👉 {M}{B}{auth_url}{X}\n")
    print(f"{DIM}Flow ID: {flow_id} | Polling interval: {init_res['poll_interval_sec']}s (Timeout: {args.timeout}s)...{X}")

    try:
        res = poll_cli_login(
            flow_id=flow_id,
            poll_token=poll_token,
            region=args.region,
            timeout_s=args.timeout,
            poll_interval_sec=init_res["poll_interval_sec"],
            proxy=args.proxy,
        )

        api_key = res["api_key"]
        print(f"\n{G}{B}✓ Login Berhasil Diotorisasi!{X}")
        print(f"  {DIM}UID      :{X} {W}{res.get('uid') or '-'}{X}")
        print(f"  {DIM}API Key  :{X} {G}{api_key[:12]}...{api_key[-6:]}{X}")
        print(f"  {DIM}Endpoint :{X} {C}{res['api_base']}{X}")

        # Save record
        record = {
            "api_key": api_key,
            "uid": res.get("uid"),
            "region": args.region,
            "api_base": res["api_base"],
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "session": res.get("login_state", {}),
        }
        saved_path = save_key_record(record)
        print(f"  {DIM}Saved to :{X} {W}{saved_path}{X}")

        if args.sync_router:
            print(f"\n{C}Menyinkronkan API key ke 9Router...{X}")
            ok = submit_stepfun_key_to_9router(api_key, name=f"StepFun Plan ({args.region})", region=args.region)
            if ok:
                print(f"{G}{B}✓ 9Router Sync Berhasil! Model 'step/step-5-preview' & 'step/step-3.7-flash' aktif.{X}")
            else:
                print(f"{R}✗ Gagal sinkronisasi ke 9Router.{X}")

    except Exception as e:
        print(f"\n{R}{B}✗ Login Gagal / Batal:{X} {R}{e}{X}")
        sys.exit(1)


def cmd_test(args: argparse.Namespace) -> None:
    api_key = args.api_key
    if not api_key:
        # Load from saved
        saved = BASE_DIR / "data" / "stepfun_keys.json"
        if saved.exists():
            records = json.loads(saved.read_text())
            if records:
                api_key = records[-1]["api_key"]

    if not api_key:
        print(f"{R}Error: Berikan --api-key atau jalankan 'login' terlebih dahulu.{X}")
        sys.exit(1)

    base_url = REGIONS[args.region]["api_base"]
    print(f"\n{C}Testing StepFun Completion via {base_url}...{X}")
    client = StepFunClient(api_key=api_key, base_url=base_url, proxy=args.proxy)

    try:
        reply = client.test_completion(model=args.model, prompt="Say 'StepFun connected successfully!'")
        print(f"{G}{B}✓ Response dari {args.model}:{X}\n{reply}\n")
    except Exception as e:
        print(f"{R}{B}✗ Test Completion Gagal:{X} {R}{e}{X}")
        sys.exit(1)


def cmd_sync_router(args: argparse.Namespace) -> None:
    api_key = args.api_key
    if not api_key:
        saved = BASE_DIR / "data" / "stepfun_keys.json"
        if saved.exists():
            records = json.loads(saved.read_text())
            if records:
                api_key = records[-1]["api_key"]

    if not api_key:
        print(f"{R}Error: Berikan --api-key atau jalankan 'login' terlebih dahulu.{X}")
        sys.exit(1)

    print(f"{C}Menyinkronkan API Key StepFun ke 9Router...{X}")
    ok = submit_stepfun_key_to_9router(api_key, name=args.name, region=args.region)
    if ok:
        print(f"{G}{B}✓ Berhasil terdaftar di 9Router (Node ID: openai-compatible-chat-stepfun-plan){X}")
        print(f"  Model aktif: step/step-5-preview, step/step-3.7-flash, step/step-3.5-flash")
    else:
        print(f"{R}✗ Gagal sinkronisasi ke database 9Router.{X}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="StepFun Suite — Reverse-Engineered Automation & 9Router Integration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # login command
    p_login = sub.add_parser("login", help="Start StepFun Outbound CLI OAuth Login flow")
    p_login.add_argument("--region", default="oversea", choices=["oversea", "cn"], help="Region (oversea: .ai, cn: .com)")
    p_login.add_argument("--timeout", type=int, default=300, help="Poll timeout in seconds")
    p_login.add_argument("--sync-router", action="store_true", help="Automatically inject API key into 9Router")
    p_login.add_argument("--proxy", help="Optional proxy URL (http://user:pass@host:port)")
    p_login.set_defaults(func=cmd_login)

    # test command
    p_test = sub.add_parser("test", help="Test chat completion on Step Plan endpoint")
    p_test.add_argument("--api-key", help="StepFun API key (defaults to last saved key)")
    p_test.add_argument("--model", default="step-3.5-flash", help="Model to test (step-5-preview, step-3.7-flash, step-3.5-flash)")
    p_test.add_argument("--region", default="oversea", choices=["oversea", "cn"])
    p_test.add_argument("--proxy", help="Optional proxy URL")
    p_test.set_defaults(func=cmd_test)

    # sync command
    p_sync = sub.add_parser("sync-router", help="Sync API key to 9Router database")
    p_sync.add_argument("--api-key", help="StepFun API key (defaults to last saved key)")
    p_sync.add_argument("--name", default="StepFun Plan Key", help="Connection label in 9Router")
    p_sync.add_argument("--region", default="oversea", choices=["oversea", "cn"])
    p_sync.set_defaults(func=cmd_sync_router)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
