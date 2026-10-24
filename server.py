#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
StepFun Studio OpenAI-Compatible Server.
Exposes a standard OpenAI /v1 endpoint backed by StepFun AI Studio sessions.
Provides free, uncensored Step 5 Preview reasoning completions.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from src.studio_relay import StepFunStudioRelay

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("StepFunServer")

PORT = 8795
DATA_FILE = BASE_DIR / "data" / "stepfun_keys.json"


def load_relays() -> list[StepFunStudioRelay]:
    if not DATA_FILE.exists():
        return []
    try:
        records = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []

    relays = []
    for rec in records:
        session = rec.get("session", {})
        acc = session.get("access_token")
        ref = session.get("refresh_token")
        dev = session.get("device_id")
        if acc and ref and dev:
            token = f"{acc}...{ref}"
            relays.append(StepFunStudioRelay(oasis_token=token, oasis_webid=dev, email=rec.get("email"), data_file=str(DATA_FILE)))
    return relays


class StepFunHTTPHandler(BaseHTTPRequestHandler):
    relays: list[StepFunStudioRelay] = []
    relay_idx: int = 0

    @classmethod
    def get_relay(cls) -> StepFunStudioRelay:
        if not cls.relays:
            cls.relays = load_relays()
        if not cls.relays:
            raise RuntimeError("No active StepFun Studio sessions found. Run 'python3 main.py auto' first.")
        relay = cls.relays[cls.relay_idx % len(cls.relays)]
        cls.relay_idx += 1
        return relay

    def do_GET(self):
        if self.path in ("/v1/models", "/models"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            models_data = {
                "object": "list",
                "data": [
                    {
                        "id": "step-5-preview",
                        "object": "model",
                        "created": int(time.time()),
                        "owned_by": "stepfun",
                        "name": "Step 5 Preview (Studio Relay)",
                        "context_length": 1000000,
                        "max_input_tokens": 1000000,
                        "max_output_tokens": 128000,
                    },
                    {
                        "id": "step-3.5-flash",
                        "object": "model",
                        "created": int(time.time()),
                        "owned_by": "stepfun",
                        "name": "Step 3.5 Flash (Studio Relay)",
                        "context_length": 256000,
                        "max_input_tokens": 256000,
                        "max_output_tokens": 65536,
                    },
                ],
            }
            self.wfile.write(json.dumps(models_data).encode("utf-8"))
        elif self.path in ("/healthz", "/health"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path in ("/v1/chat/completions", "/chat/completions"):
            length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(length)
            try:
                body = json.loads(raw_body)
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
                return

            messages = body.get("messages", [])
            tools = body.get("tools")
            model = body.get("model", "step-5-preview")
            # Strip prefixes if any
            if "/" in model:
                model = model.split("/")[-1]

            # Model routing & fallbacks for Web Studio supported models
            if model in ("step-3.5-flash", "step-3-flash", "step-3"):
                model = "step-3.7-flash"
            elif model not in ("step-5-preview", "step-3.7-flash"):
                model = "step-5-preview"

            temperature = float(body.get("temperature", 1.0))
            top_p = float(body.get("top_p", 0.95))
            max_tokens = int(body.get("max_tokens", 4096))
            is_stream = bool(body.get("stream", False))

            try:
                relay = self.get_relay()
                if is_stream:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "keep-alive")
                    self.end_headers()

                    stream_gen = relay.chat_completion(
                        messages=messages,
                        tools=tools,
                        model=model,
                        temperature=temperature,
                        top_p=top_p,
                        max_tokens=max_tokens,
                        thinking=True,
                        stream=True,
                    )
                    for chunk in stream_gen:
                        try:
                            self.wfile.write(chunk.encode("utf-8"))
                            self.wfile.flush()
                        except (BrokenPipeError, ConnectionResetError):
                            break
                else:
                    res = relay.chat_completion(
                        messages=messages,
                        tools=tools,
                        model=model,
                        temperature=temperature,
                        top_p=top_p,
                        max_tokens=max_tokens,
                        thinking=True,
                        stream=False,
                    )
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(res).encode("utf-8"))
            except Exception as e:
                logger.error("Relay processing error: %s", e)
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": {"message": str(e), "type": "relay_error"}}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()


def run_server(port: int = PORT):
    logger.info("Initializing StepFun Studio Relay Server on port %d...", port)
    StepFunHTTPHandler.relays = load_relays()
    logger.info("Loaded %d active StepFun Studio session(s).", len(StepFunHTTPHandler.relays))

    server = ThreadingHTTPServer(("127.0.0.1", port), StepFunHTTPHandler)
    logger.info("Server running at http://127.0.0.1:%d/v1", port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Stopping server...")
        server.server_close()


if __name__ == "__main__":
    run_server()
