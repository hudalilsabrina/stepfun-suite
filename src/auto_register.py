"""
StepFun End-to-End Autonomous Account Creator & API Key Harvester.
Orchestrates:
1. Tempik temporary mail provisioning
2. StepFun CLI OAuth flow initiation
3. Account creation with Tencent TCaptcha slider solving
4. OTP verification
5. Web session CLI-Login authorization
6. Automatic 9Router gateway synchronization
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

# Add parent directory
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from src.tempik import TempikClient
from src.oauth_login import start_cli_login, poll_cli_login
from src.router_sync import submit_stepfun_key_to_9router
from src.tcaptcha.network import NetworkTap
from src.tcaptcha import detect as t_detect
from src.tcaptcha import drag as t_drag
from src.tcaptcha import risk as t_risk

logger = logging.getLogger("StepFunAutoRegister")

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36")


def solve_tcaptcha(page, cap: dict, timeout_s: float = 25.0) -> bool:
    """Waits for and solves the Tencent TCaptcha slider on the active page."""
    frame = None
    start = time.time()
    while time.time() - start < timeout_s:
        found = next((f for f in page.frames if "captcha" in (f.url or "") or "gtimg" in (f.url or "")), None)
        if found and cap.get("prehandle_resp"):
            frame = found
            break
        page.wait_for_timeout(500)

    if not frame or not cap.get("prehandle_resp"):
        logger.error("TCaptcha iframe or prehandle response not found.")
        return False

    logger.info("TCaptcha frame attached. Waiting for puzzle images...")
    ctx = page.context
    steps = 40
    for i in range(steps):
        if cap.get("images", {}).get("bg") and cap.get("images", {}).get("fg"):
            break
        if i % 4 == 3:
            for key in ("bg", "fg"):
                if cap.get("images", {}).get(key):
                    continue
                url = cap.get("image_urls", {}).get(key)
                if url:
                    try:
                        rr = ctx.request.get(url, timeout=10000)
                        if rr.ok:
                            cap["images"][key] = rr.body()
                    except Exception:
                        pass
        page.wait_for_timeout(500)

    bg_b = cap.get("images", {}).get("bg")
    fg_b = cap.get("images", {}).get("fg")
    if not bg_b or not fg_b:
        logger.error("Failed to acquire challenge images.")
        return False

    try:
        piece, logical = t_risk.challenge_geometry(cap["prehandle_resp"])
    except Exception as e:
        logger.error("Failed to parse challenge geometry: %s", e)
        return False

    det = t_detect.detect(bg_b, fg_b, piece)
    cands = t_detect.candidates(det)
    verdict = t_detect.cluster(det)

    if not cands or not verdict.get("agree"):
        logger.warning("Detectors do not agree (blocker: %s). Falling back to top cluster.", verdict.get("blocker"))
        # Fallback to best guess
        top_x = verdict.get("dark_x") or (verdict.get("top", {}) or {}).get("x") or piece["init_pos"][0] + 120
        cands["drag_target"] = {
            "x": top_x,
            "y": piece["init_pos"][1],
            "dx": top_x - piece["init_pos"][0],
            "_label": "fallback",
        }

    candidate = cands.get("drag_target") or next(iter(cands.values()))
    logger.info("Computed drag candidate: dx=%d (target_x=%d)", candidate["dx"], candidate["x"])

    drag_res = t_drag.execute(page, frame, logical, candidate)
    if not drag_res:
        logger.error("Failed to execute mouse drag.")
        return False

    # Wait for verify response
    for _ in range(30):
        page.wait_for_timeout(500)
        if cap.get("verify_resp"):
            break

    verify_raw = cap.get("verify_resp", "")
    err_code = t_risk.parse_verify(verify_raw)
    logger.info("TCaptcha verify response: errorCode=%s", err_code)
    return err_code == "0"


def run_autonomous_registration(
    region: str = "oversea",
    sync_router: bool = True,
    proxy: Optional[str] = None,
    timeout_s: int = 300,
) -> Dict[str, Any]:
    from playwright.sync_api import sync_playwright

    logger.info("Step 1: Provisioning disposable email via Tempik...")
    tempik = TempikClient(proxy=proxy)
    email = tempik.create_inbox(domain="xentranetwork.me")
    logger.info("Tempik inbox created: %s", email)

    logger.info("Step 2: Starting StepFun CLI OAuth session...")
    login_init = start_cli_login(region=region, proxy=proxy)
    flow_id = login_init["flow_id"]
    poll_token = login_init["poll_token"]
    auth_url = login_init["authorize_url"]
    logger.info("Remote Authorization URL: %s", auth_url)

    logger.info("Step 3: Launching browser automation for account registration...")
    launch_args = ["--no-sandbox", "--disable-blink-features=AutomationControlled"]
    proxy_cfg = {"server": proxy} if proxy else None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=launch_args, proxy=proxy_cfg)
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()

        cap = NetworkTap.blank()
        NetworkTap.attach(page, cap)

        login_url = "https://account.stepfun.ai/login?redirect=https%3A%2F%2Fplatform.stepfun.ai%2F&source_app=platform-oversea"
        page.goto(login_url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_selector("input[type=email]", timeout=30000)
        page.wait_for_timeout(1000)

        logger.info("Filling email address: %s", email)
        page.fill("input[type=email]", email)
        page.wait_for_timeout(600)

        logger.info("Triggering 'Get code' button...")
        get_code_btn = page.get_by_text("Get code", exact=True)
        get_code_btn.click()
        page.wait_for_timeout(2000)

        # Solve TCaptcha
        logger.info("Solving Tencent TCaptcha slider...")
        solved = solve_tcaptcha(page, cap, timeout_s=30.0)
        if not solved:
            page.screenshot(path="/tmp/stepfun_captcha_failed.png")
            raise RuntimeError("TCaptcha solve failed.")

        logger.info("TCaptcha solved! Verification code sent to email.")

        # Step 4: Poll Tempik for OTP
        otp = tempik.poll_for_otp(email, timeout_sec=90)
        if not otp:
            page.screenshot(path="/tmp/stepfun_otp_failed.png")
            raise TimeoutError(f"OTP not received in email {email} within 90s.")

        logger.info("Entering OTP: %s", otp)
        code_input = page.query_selector("input[placeholder*='code' i]") or page.query_selector("input[type=text]")
        if not code_input:
            raise RuntimeError("Verification code input not found.")
        code_input.fill(otp)
        page.wait_for_timeout(500)

        # Click Terms agreement checkbox (Radix UI role="checkbox")
        logger.info("Accepting User Agreement & Privacy Policy...")
        cb = page.query_selector("button[role='checkbox']")
        if cb:
            if cb.get_attribute("data-state") != "checked":
                cb.click()
                page.wait_for_timeout(400)
        else:
            page.evaluate("""() => {
                const b = document.querySelector("button[role='checkbox']");
                if (b && b.getAttribute('data-state') !== 'checked') b.click();
            }""")
            page.wait_for_timeout(400)

        # Click Sign in / Sign up
        logger.info("Submitting registration...")
        submit_btn = page.get_by_role("button", name=re.compile(r"sign\s*(in|up)", re.I)).first
        if not submit_btn or not submit_btn.is_visible():
            submit_btn = page.query_selector("button[type=submit]") or page.get_by_text("Sign in / Sign up")
        submit_btn.click()
        page.wait_for_timeout(2000)

        # Wait for redirect away from account.stepfun.ai
        logger.info("Waiting for successful account authentication (redirect to platform)...")
        for i in range(25):
            page.wait_for_timeout(1000)
            if "account.stepfun.ai" not in page.url or "/login" not in page.url:
                logger.info("Login redirect confirmed: %s", page.url)
                break

        page.wait_for_timeout(2000)

        # Step 5: Authorize CLI-Login session
        logger.info("Navigating to CLI-Login remote authorization page: %s", auth_url)
        page.goto(auth_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)

        # Wait for "Authorize access" button to appear
        logger.info("Waiting for 'Authorize access' button...")
        try:
            page.wait_for_selector("button:has-text('Authorize access')", timeout=20000)
        except Exception:
            pass

        auth_btn = page.query_selector("button:has-text('Authorize access')") or page.get_by_role("button", name=re.compile(r"Authorize", re.I)).first
        if auth_btn and auth_btn.is_visible():
            logger.info("Clicking 'Authorize access' button...")
            auth_btn.click()
        else:
            logger.info("Fallback clicking authorize button via DOM...")
            page.evaluate("""() => {
                const btns = [...document.querySelectorAll('button')];
                const target = btns.find(b => /(authorize|confirm|approve)/i.test(b.innerText || ''));
                if (target) target.click();
            }""")

        # Wait until page says approved or authorized
        logger.info("Waiting for authorization confirmation...")
        for _ in range(20):
            page.wait_for_timeout(1000)
            txt = page.inner_text("body").lower()
            if "approved" in txt or "has been authorized" in txt:
                logger.info("Authorization confirmed in browser DOM!")
                break

        page.screenshot(path="/tmp/stepfun_auth_success.png")
        page.wait_for_timeout(1000)
        browser.close()

    # Step 6: Poll for minted API Key
    logger.info("Step 6: Polling CLI login token...")
    result = poll_cli_login(
        flow_id=flow_id,
        poll_token=poll_token,
        region=region,
        timeout_s=timeout_s,
        poll_interval_sec=2,
        proxy=proxy,
    )

    api_key = result["api_key"]
    logger.info("Acquired StepFun API Key: %s...%s", api_key[:10], api_key[-6:])

    record = {
        "email": email,
        "api_key": api_key,
        "uid": result.get("uid"),
        "region": region,
        "api_base": result["api_base"],
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "session": result.get("login_state", {}),
    }

    # Save to data/stepfun_keys.json
    out_dir = BASE_DIR / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "stepfun_keys.json"
    records = []
    if out_file.exists():
        try:
            records = json.loads(out_file.read_text())
        except Exception:
            records = []
    records.append(record)
    out_file.write_text(json.dumps(records, indent=2))
    os.chmod(out_file, 0o600)

    if sync_router:
        logger.info("Syncing API Key to 9Router gateway...")
        submit_stepfun_key_to_9router(api_key, name=f"StepFun ({email})", region=region)

    return record
