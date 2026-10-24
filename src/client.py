"""
StepFun Step Plan API Client.
Interfaces with StepFun Step Plan OpenAI-compatible completions and ConnectRPC dashboard APIs.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional
import requests

logger = logging.getLogger("StepFunClient")

DEFAULT_OVERSEA_BASE = "https://api.stepfun.ai/step_plan/v1"
DEFAULT_CN_BASE = "https://api.stepfun.com/step_plan/v1"


class StepFunClient:
    def __init__(self, api_key: str, base_url: str = DEFAULT_OVERSEA_BASE, proxy: Optional[str] = None):
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.proxies = {"http": proxy, "https": proxy} if proxy else None
        self.session = requests.Session()
        if self.proxies:
            self.session.proxies.update(self.proxies)

    @property
    def headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def list_models(self) -> List[Dict[str, Any]]:
        """Fetches models available on the Step Plan endpoint."""
        url = f"{self.base_url}/models"
        resp = self.session.get(url, headers=self.headers, timeout=15)
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to list models (HTTP {resp.status_code}): {resp.text}")
        data = resp.json()
        return data.get("data", [])

    def test_completion(self, model: str = "step-3.5-flash", prompt: str = "Hi, reply with 'OK' only.") -> str:
        """Executes a smoke test chat completion."""
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 50,
            "stream": False,
        }
        resp = self.session.post(url, headers=self.headers, json=payload, timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(f"Completion failed (HTTP {resp.status_code}): {resp.text}")

        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError(f"No choices returned: {data}")
        return choices[0].get("message", {}).get("content", "").strip()

    @staticmethod
    def query_dashboard_limits(
        oasis_token: str,
        oasis_webid: str = "bfe7df2615d72de9fb91c7be9abb5b9105127d5d",
        region: str = "oversea",
        proxy: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Queries live rate-limit and subscription usage from StepFun DevCenter via ConnectRPC.
        """
        origin = "https://platform.stepfun.ai" if region == "oversea" else "https://platform.stepfun.com"
        url = f"{origin}/api/step.openapi.devcenter.Dashboard/QueryStepPlanRateLimit"
        headers = {
            "Content-Type": "application/json",
            "connect-protocol-version": "1",
            "oasis-appid": "20700",
            "oasis-platform": "web",
            "oasis-webid": oasis_webid,
            "Cookie": f"Oasis-Token={oasis_token}",
        }
        proxies = {"http": proxy, "https": proxy} if proxy else None
        resp = requests.post(url, headers=headers, json={}, proxies=proxies, timeout=15)
        if resp.status_code != 200:
            raise RuntimeError(f"RateLimit query failed (HTTP {resp.status_code}): {resp.text}")
        return resp.json()
