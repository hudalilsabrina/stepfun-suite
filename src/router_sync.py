"""
9Router Synchronization Module for StepFun (Step Plan).
Automatically registers the StepFun provider node, custom models, and credentials into 9Router SQLite.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("StepFunRouterSync")

STEPFUN_NODE_ID = "openai-compatible-chat-stepfun-plan"
STEPFUN_PREFIX = "step"
STEPFUN_OVERSEA_BASE = "https://api.stepfun.ai/step_plan/v1"
STEPFUN_CN_BASE = "https://api.stepfun.com/step_plan/v1"

STEPFUN_MODELS = [
    {
        "id": "step-5-preview",
        "name": "Step 5 Preview (Reasoning Flagship)",
        "caps": {
            "vision": True,
            "reasoning": True,
            "thinkDeeper": True,
            "speedMode": False,
            "jsonGuard": False,
            "contextSqueezer": False,
        },
    },
    {
        "id": "step-3.7-flash",
        "name": "Step 3.7 Flash",
        "caps": {
            "vision": True,
            "reasoning": True,
            "thinkDeeper": False,
            "speedMode": True,
            "jsonGuard": False,
            "contextSqueezer": False,
        },
    },
    {
        "id": "step-3.5-flash",
        "name": "Step 3.5 Flash",
        "caps": {
            "vision": True,
            "reasoning": False,
            "thinkDeeper": False,
            "speedMode": True,
            "jsonGuard": False,
            "contextSqueezer": False,
        },
    },
]


def get_9router_db_path() -> Path:
    candidates = [
        Path("/var/lib/9router/db/data.sqlite"),
        Path.home() / ".config" / "9router" / "db" / "data.sqlite",
        Path.home() / ".9router" / "db" / "data.sqlite",
    ]
    if sys.platform == "win32":
        appdata = os.getenv("APPDATA")
        if appdata:
            candidates.insert(0, Path(appdata) / "9router" / "db" / "data.sqlite")

    for p in candidates:
        if p.exists():
            return p
    return Path("/var/lib/9router/db/data.sqlite")


def ensure_stepfun_node_exists(conn: sqlite3.Connection, base_url: str = STEPFUN_OVERSEA_BASE) -> None:
    """Upserts StepFun providerNode & customModels into 9Router SQLite."""
    cur = conn.cursor()
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    node_data = {
        "prefix": STEPFUN_PREFIX,
        "apiType": "chat",
        "baseUrl": base_url,
        "logo": "",
    }

    # 1. Upsert providerNodes
    cur.execute(
        """INSERT INTO providerNodes (id, type, name, data, createdAt, updatedAt)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             type=excluded.type, name=excluded.name, data=excluded.data, updatedAt=excluded.updatedAt""",
        (STEPFUN_NODE_ID, "openai-compatible", "StepFun Step Plan", json.dumps(node_data), now_iso, now_iso),
    )

    # 2. Register models in kv table with scope='customModels'
    for m in STEPFUN_MODELS:
        model_kv = {
            "providerAlias": STEPFUN_PREFIX,
            "id": m["id"],
            "type": "llm",
            "name": m["name"],
            "caps": m["caps"],
        }
        kv_key = f"{STEPFUN_PREFIX}|{m['id']}|llm"
        cur.execute(
            """INSERT INTO kv (scope, key, value)
               VALUES (?, ?, ?)
               ON CONFLICT(scope, key) DO UPDATE SET value=excluded.value""",
            ("customModels", kv_key, json.dumps(model_kv)),
        )

    conn.commit()
    logger.info("Registered StepFun node & %d custom models in 9Router.", len(STEPFUN_MODELS))


def submit_stepfun_key_to_9router(
    api_key: str,
    name: str = "StepFun Plan Key",
    region: str = "oversea",
    db_path: Optional[Path | str] = None,
) -> bool:
    """Inserts a StepFun API key into 9Router providerConnections."""
    target_path = Path(db_path) if db_path else get_9router_db_path()
    if not target_path.exists():
        logger.warning("9Router SQLite DB not found at %s", target_path)
        return False

    base_url = STEPFUN_OVERSEA_BASE if region == "oversea" else STEPFUN_CN_BASE
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    conn_data = {
        "defaultModel": f"{STEPFUN_PREFIX}/step-3.5-flash",
        "apiKey": api_key,
        "testStatus": "active",
        "providerSpecificData": {
            "prefix": STEPFUN_PREFIX,
            "apiType": "chat",
            "baseUrl": base_url,
            "nodeName": "StepFun Step Plan",
            "connectionProxyEnabled": False,
            "connectionProxyUrl": "",
            "connectionNoProxy": "",
        },
        "lastError": None,
        "lastErrorAt": None,
        "errorCode": None,
        "backoffLevel": 0,
    }

    try:
        conn = sqlite3.connect(str(target_path))
        ensure_stepfun_node_exists(conn, base_url=base_url)

        cur = conn.cursor()
        # Check if already present
        cur.execute(
            "SELECT id, data FROM providerConnections WHERE provider = ? AND isActive = 1",
            (STEPFUN_NODE_ID,),
        )
        rows = cur.fetchall()
        for cid, raw_d in rows:
            try:
                parsed = json.loads(raw_d)
                if parsed.get("apiKey") == api_key:
                    logger.info("API key already registered in connection id=%s", cid)
                    conn.close()
                    return True
            except Exception:
                pass

        new_id = str(uuid.uuid4())
        cur.execute(
            """INSERT INTO providerConnections (id, provider, name, isActive, authType, data, createdAt, updatedAt)
               VALUES (?, ?, ?, 1, 'apikey', ?, ?, ?)""",
            (new_id, STEPFUN_NODE_ID, name, json.dumps(conn_data), now_iso, now_iso),
        )
        conn.commit()
        conn.close()
        logger.info("Successfully registered StepFun connection id=%s to 9Router.", new_id)
        return True
    except Exception as e:
        logger.error("Failed to inject StepFun key to 9Router: %s", e)
        return False
