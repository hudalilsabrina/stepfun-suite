"""
Tempik Client — Disposable temporary mail client for Cloudflare Workers (mail.xentranetwork.me).
"""

from __future__ import annotations

import logging
import random
import re
import string
import time
from typing import Optional
import requests

logger = logging.getLogger("Tempik")

TEMPIK_BASE = "https://mail.xentranetwork.me"
DEFAULT_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36")


def random_string(n: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


class TempikClient:
    def __init__(self, base_url: str = TEMPIK_BASE, proxy: Optional[str] = None):
        self.base = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": DEFAULT_UA})
        if proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})
        self.session_id: Optional[str] = None
        self._init_session()

    def _init_session(self) -> None:
        r = self.session.get(f"{self.base}/api/session", timeout=20)
        if r.status_code != 200:
            raise RuntimeError(f"Failed to init Tempik session (HTTP {r.status_code}): {r.text}")
        self.session_id = r.json().get("sessionId")
        self.session.headers.update({"x-session-id": self.session_id})

    def create_inbox(self, domain: str = "xentranetwork.me", local_part: Optional[str] = None) -> str:
        local_part = local_part or f"sf_{int(time.time())}_{random_string(4)}"
        r = self.session.post(
            f"{self.base}/api/inboxes",
            headers={"Content-Type": "application/json"},
            json={"domain": domain, "localPart": local_part},
            timeout=20,
        )
        if r.status_code not in (200, 201):
            raise RuntimeError(f"Failed to create inbox in Tempik: {r.status_code} {r.text}")
        return r.json()["address"]

    def poll_for_otp(self, address: str, timeout_sec: int = 90, interval: int = 3) -> Optional[str]:
        start = time.time()
        logger.info("Waiting for OTP email in %s (timeout %ds)...", address, timeout_sec)
        while time.time() - start < timeout_sec:
            try:
                r = self.session.get(f"{self.base}/api/inboxes/{address}/messages", timeout=15)
                if r.status_code == 200:
                    msgs = r.json()
                    if msgs:
                        msg_id = msgs[0]["id"]
                        r_det = self.session.get(f"{self.base}/api/inboxes/{address}/messages/{msg_id}", timeout=15)
                        det = r_det.json() if r_det.status_code == 200 else msgs[0]
                        body = det.get("body") or det.get("html") or det.get("text") or str(det)
                        # StepFun uses 6-digit verification code
                        m = re.search(r'\b([0-9]{6})\b', body)
                        if m:
                            code = m.group(1)
                            logger.info("Found OTP: %s", code)
                            return code
            except Exception as e:
                logger.warning("Tempik polling retry: %s", e)
            time.sleep(interval)
        return None
