"""
StepFun Studio Web-to-API Relay Adapter.
Bypasses the locked prepaid API quota by relaying OpenAI-compatible chat completions
directly to StepFun AI Studio (https://studio.stepfun.ai/api/stdhttp/v1/studio/stream).
Unlocks Step 5 Preview with full 128K context & thinking support.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Dict, Generator, List, Optional
import requests

logger = logging.getLogger("StepFunStudioRelay")

STUDIO_STREAM_URL = "https://studio.stepfun.ai/api/stdhttp/v1/studio/stream"
STUDIO_CREATE_CONV_URL = "https://studio.stepfun.ai/api/step.openapi.devcenter.Dashboard/CreateConversation"


class StepFunStudioRelay:
    def __init__(self, oasis_token: str, oasis_webid: str, proxy: Optional[str] = None):
        self.oasis_token = oasis_token
        self.oasis_webid = oasis_webid
        self.proxies = {"http": proxy, "https": proxy} if proxy else None
        self.session = requests.Session()
        if self.proxies:
            self.session.proxies.update(self.proxies)

    def refresh_session_token(self) -> bool:
        """Refreshes the Oasis-Token using Passport RefreshToken procedure."""
        try:
            url = "https://account.stepfun.ai/passport/proto.api.passport.v1.PassportService/RefreshToken"
            headers = {
                "Content-Type": "application/json",
                "connect-protocol-version": "1",
                "Oasis-appID": "20700",
                "Oasis-Platform": "web",
                "Oasis-Webid": self.oasis_webid,
                "Cookie": f"Oasis-Token={self.oasis_token}",
            }
            r = self.session.post(url, headers=headers, json={}, timeout=10)
            if r.status_code == 200:
                data = r.json()
                acc = data.get("accessToken", {}).get("raw")
                ref = data.get("refreshToken", {}).get("raw")
                if acc and ref:
                    self.oasis_token = f"{acc}...{ref}"
                    logger.info("Session token refreshed successfully.")
                    return True
        except Exception as e:
            logger.warning("Token refresh failed: %s", e)
        return False

    @property
    def headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "connect-protocol-version": "1",
            "Oasis-appID": "20700",
            "Oasis-Platform": "web",
            "Oasis-Webid": self.oasis_webid,
            "Cookie": f"Oasis-Token={self.oasis_token}",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
            "Origin": "https://studio.stepfun.ai",
            "Referer": "https://studio.stepfun.ai/",
        }

    def create_conversation(self) -> Optional[str]:
        """Creates a new conversation container on AI Studio."""
        try:
            r = self.session.post(
                STUDIO_CREATE_CONV_URL,
                headers=self.headers,
                json={"type": "CONVERSATION_TYPE_CHAT"},
                timeout=10,
            )
            if r.status_code == 200:
                data = r.json()
                return data.get("conversation", {}).get("conversationId") or data.get("conversationId")
        except Exception as e:
            logger.warning("Failed to create conversation: %s", e)
        return None

    def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        model: str = "step-5-preview",
        temperature: float = 1.0,
        top_p: float = 0.95,
        max_tokens: int = 4096,
        thinking: bool = True,
        stream: bool = False,
    ) -> Any:
        # Flatten messages to single query if needed, or take the last user message + system context
        system_prompt = ""
        user_prompt = ""
        for m in messages:
            role = m.get("role", "")
            content = m.get("content", "")
            if isinstance(content, list):
                # Multimodal or parts
                content = " ".join([p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"])
            if role == "system":
                system_prompt += f"{content}\n\n"
            elif role == "user":
                user_prompt = content
            elif role == "assistant":
                system_prompt += f"Previous Assistant Response: {content}\n"

        full_content = f"{system_prompt}User: {user_prompt}".strip() if system_prompt else user_prompt

        conv_id = self.create_conversation()
        payload = {
            "conversation_id": conv_id,
            "kind": "chat",
            "chat": {
                "model": {
                    "model_id": model,
                    "config": {
                        "max_tokens": max_tokens,
                        "temperature": temperature,
                        "top_p": top_p,
                        "frequency_penalty": 0,
                        "thinking": thinking,
                        "effort": "medium",
                    },
                },
                "content": full_content,
                "asset_ids": [],
                "enable_web_search": False,
            },
        }

        r = self.session.post(STUDIO_STREAM_URL, headers=self.headers, json=payload, stream=True, timeout=60)
        if r.status_code == 401:
            logger.info("Received HTTP 401, attempting auto-refresh of Oasis-Token...")
            if self.refresh_session_token():
                r = self.session.post(STUDIO_STREAM_URL, headers=self.headers, json=payload, stream=True, timeout=60)

        if r.status_code != 200:
            raise RuntimeError(f"Studio API error (HTTP {r.status_code}): {r.text[:300]}")

        if stream:
            return self._stream_generator(r, model)
        else:
            return self._accumulate_response(r, model)

    def _stream_generator(self, resp: requests.Response, model: str) -> Generator[str, None, None]:
        cmpl_id = f"chatcmpl-{uuid.uuid4().hex[:16]}"
        created = int(time.time())

        for line in resp.iter_lines():
            if not line:
                continue
            line = line.decode("utf-8", errors="ignore")
            if not line.startswith("data:"):
                continue

            raw_str = line[5:].strip()
            if not raw_str:
                continue

            try:
                evt = json.loads(raw_str)
                evt_type = evt.get("type")
                data = evt.get("data", {})

                delta = {}
                if evt_type == "reasoning_delta":
                    delta["reasoning_content"] = data.get("delta", "")
                elif evt_type == "text_delta":
                    delta["content"] = data.get("delta", "")
                elif evt_type == "done":
                    # Send [DONE]
                    chunk = {
                        "id": cmpl_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": model,
                        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    }
                    yield f"data: {json.dumps(chunk)}\n\n"
                    yield "data: [DONE]\n\n"
                    break

                if delta:
                    chunk = {
                        "id": cmpl_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": model,
                        "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
                    }
                    yield f"data: {json.dumps(chunk)}\n\n"
            except Exception:
                continue

    def _accumulate_response(self, resp: requests.Response, model: str) -> Dict[str, Any]:
        cmpl_id = f"chatcmpl-{uuid.uuid4().hex[:16]}"
        created = int(time.time())
        reasoning_pieces = []
        content_pieces = []
        tokens_in = 0
        tokens_out = 0

        for line in resp.iter_lines():
            if not line:
                continue
            line = line.decode("utf-8", errors="ignore")
            if not line.startswith("data:"):
                continue

            raw_str = line[5:].strip()
            if not raw_str:
                continue

            try:
                evt = json.loads(raw_str)
                evt_type = evt.get("type")
                data = evt.get("data", {})

                if evt_type == "reasoning_delta":
                    reasoning_pieces.append(data.get("delta", ""))
                elif evt_type == "text_delta":
                    content_pieces.append(data.get("delta", ""))
                elif evt_type == "final":
                    usage = data.get("usage", {})
                    tokens_in = int(usage.get("tokens_in", 0))
                    tokens_out = int(usage.get("tokens_out", 0))
            except Exception:
                pass

        full_reasoning = "".join(reasoning_pieces)
        full_content = "".join(content_pieces)

        return {
            "id": cmpl_id,
            "object": "chat.completion",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": full_content,
                        "reasoning_content": full_reasoning if full_reasoning else None,
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": tokens_in,
                "completion_tokens": tokens_out,
                "total_tokens": tokens_in + tokens_out,
            },
        }
