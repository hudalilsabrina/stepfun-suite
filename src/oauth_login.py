"""
StepFun CLI Outbound OAuth Handler.
Implements the reverse-engineered cloud-polled device authentication flow from Step Code.
"""

from __future__ import annotations

import logging
import secrets
import time
from typing import Any, Dict, Optional
import requests

logger = logging.getLogger("StepFunOAuth")

REGIONS = {
    "oversea": {
        "origin": "https://platform.stepfun.ai",
        "profile": "step_plan_oversea",
        "api_base": "https://api.stepfun.ai/step_plan/v1",
    },
    "cn": {
        "origin": "https://platform.stepfun.com",
        "profile": "step_plan",
        "api_base": "https://api.stepfun.com/step_plan/v1",
    },
}

USER_AGENT = "stepcode/1.0.0 (linux-x64)"


def start_cli_login(region: str = "oversea", proxy: Optional[str] = None) -> Dict[str, Any]:
    """
    Initializes a CLI login session with StepFun developer center.
    Returns:
        dict: {flow_id, authorize_url, poll_token, poll_interval_sec, expires_at, region}
    """
    cfg = REGIONS.get(region.lower())
    if not cfg:
        raise ValueError(f"Unknown region '{region}'. Choose 'oversea' or 'cn'.")

    origin = cfg["origin"]
    profile = cfg["profile"]
    poll_token = secrets.token_hex(32)

    headers = {
        "Authorization": f"Bearer {poll_token}",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }
    body = {
        "profile": profile,
        "origin": origin,
        "client": {
            "name": "stepcode",
            "version": "1.0.0",
            "platform": "linux-x64",
        },
    }

    proxies = {"http": proxy, "https": proxy} if proxy else None
    url = f"{origin}/api/stdhttp/v1/cli-login/init"

    logger.info("Initializing StepFun CLI login for region: %s", region)
    resp = requests.post(url, json=body, headers=headers, proxies=proxies, timeout=15)
    if resp.status_code != 200:
        raise RuntimeError(f"Init failed (HTTP {resp.status_code}): {resp.text}")

    data = resp.json()
    if data.get("status") != 0:
        raise RuntimeError(f"Init returned error status {data.get('status')}: {data.get('desc')}")

    flow_id = data.get("flow_id")
    poll_interval_sec = max(int(data.get("poll_interval_sec", 2)), 1)
    expires_at = int(data.get("expires_at", time.time() + 600))
    authorize_url = f"{origin}/cli-login-remote?flow_id={flow_id}"

    return {
        "flow_id": flow_id,
        "authorize_url": authorize_url,
        "poll_token": poll_token,
        "poll_interval_sec": poll_interval_sec,
        "expires_at": expires_at,
        "region": region,
        "api_base": cfg["api_base"],
    }


def poll_cli_login(
    flow_id: str,
    poll_token: str,
    region: str = "oversea",
    timeout_s: int = 300,
    poll_interval_sec: int = 2,
    proxy: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Polls until the user approves the login in the browser.
    Returns:
        dict: {api_key, uid, login_state, region}
    """
    cfg = REGIONS.get(region.lower())
    if not cfg:
        raise ValueError(f"Unknown region '{region}'.")

    origin = cfg["origin"]
    headers = {
        "Authorization": f"Bearer {poll_token}",
        "User-Agent": USER_AGENT,
    }
    proxies = {"http": proxy, "https": proxy} if proxy else None
    poll_url = f"{origin}/api/stdhttp/v1/cli-login/poll/{flow_id}"

    start_time = time.time()
    logger.info("Waiting for user authorization in browser at: %s/cli-login-remote?flow_id=%s", origin, flow_id)

    while time.time() - start_time < timeout_s:
        try:
            resp = requests.get(poll_url, headers=headers, proxies=proxies, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                state = data.get("state")

                if state == "pending":
                    time.sleep(poll_interval_sec)
                    continue

                if state == "ready":
                    cred = data.get("credential", {})
                    api_key = cred.get("api_key")
                    if not api_key:
                        raise RuntimeError(f"Poll ready but missing api_key: {data}")

                    logger.info("StepFun CLI login authorization succeeded!")
                    return {
                        "api_key": api_key,
                        "uid": data.get("uid"),
                        "login_state": cred.get("login", {}),
                        "region": region,
                        "api_base": cfg["api_base"],
                    }

                if state == "failed":
                    reason = data.get("reason", "unknown")
                    raise RuntimeError(f"Login failed on server: reason={reason}")

                raise RuntimeError(f"Unknown state received: {state}")
            elif resp.status_code == 404:
                raise RuntimeError("Flow expired or not found on server.")
            else:
                logger.warning("Transient poll HTTP %s: %s", resp.status_code, resp.text[:100])
        except requests.RequestException as e:
            logger.warning("Poll network error: %s", e)

        time.sleep(poll_interval_sec)

    raise TimeoutError(f"StepFun CLI login timed out after {timeout_s} seconds.")
