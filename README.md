# StepFun Suite (Step Plan & Step Code Bridge)

Reverse-engineered automation, Outbound CLI OAuth authentication, and 9Router gateway integration for **StepFun AI (阶跃星辰)**.

---

## ⚡ Background & Architecture

StepFun maintains two distinct ecosystems:
1. **Standard OpenAPI** (`https://api.stepfun.ai/v1`): Prepaid token balance. Requires credit card or pay-per-token credits.
2. **Step Plan & Step Code** (`https://api.stepfun.ai/step_plan/v1`): Subscription and internal agent harness gateway. Provides access to flagship models (`step-5-preview`, `step-3.7-flash`, `step-3.5-flash`) with dedicated rate limits.

```
+-------------------+       1. POST /cli-login/init (poll_token)      +-----------------------------+
|                   | ----------------------------------------------> |                             |
|   StepFun Suite   | <---------------------------------------------- |   StepFun Developer Center  |
|     (Client)      |       flow_id + auth_url                        |    (platform.stepfun.ai)    |
|                   |                                                 |                             |
|                   |       2. User approves in Browser               |                             |
|                   |          (cli-login-remote?flow_id=...)         |                             |
|                   |                                                 |                             |
|                   |       3. GET /cli-login/poll (poll_token)       |                             |
|                   | ----------------------------------------------> |                             |
|                   | <---------------------------------------------- |                             |
|                   |       state: ready (api_key + session)          +-----------------------------+
+-------------------+
          |
          | 4. Automatic Injection
          v
+------------------------------------+
| 9Router SQLite Gateway (:20127)    |
|  - step/step-5-preview             |
|  - step/step-3.7-flash             |
|  - step/step-3.5-flash             |
+------------------------------------+
```

---

## 🚀 Quick Start

### 1. Requirements

Requires Python 3.10+ and `requests`:
```bash
pip install -r requirements.txt
```

### 2. Run Outbound CLI Login

Execute login to generate a remote authorization link:
```bash
# Global / Overseas (platform.stepfun.ai)
python3 main.py login --region oversea --sync-router

# Domestic China (platform.stepfun.com)
python3 main.py login --region cn --sync-router
```

Output:
```
════════════════════════════════════════════════════════════════
   ⚡ STEPFUN STEP PLAN — OUTBOUND CLI LOGIN ⚡
════════════════════════════════════════════════════════════════
  Region  : oversea
  Target  : https://platform.stepfun.ai
────────────────────────────────────────────────────────────────

[ACTION REQUIRED] Buka URL berikut di browser kamu untuk approve login:

  👉 https://platform.stepfun.ai/cli-login-remote?flow_id=dccd926b4b9cbfb4a22c8931d91643be

Flow ID: dccd... | Polling interval: 2s...

✓ Login Berhasil Diotorisasi!
  UID      : 10029384
  API Key  : step_v1_abcd...1234
  Endpoint : https://api.stepfun.ai/step_plan/v1
  Saved to : /root/stepfun-suite/data/stepfun_keys.json

Menyinkronkan API key ke 9Router...
✓ 9Router Sync Berhasil! Model 'step/step-5-preview' & 'step/step-3.7-flash' aktif.
```

### 3. Test Chat Completion

Test your key against the Step Plan completions endpoint:
```bash
python3 main.py test --model step-3.5-flash
python3 main.py test --model step-5-preview
```

### 4. Sync Existing API Key to 9Router

If you already have a StepFun API key:
```bash
python3 main.py sync-router --api-key "your_step_api_key_here" --name "My StepFun Key"
```

---

## 🧩 Supported Models in 9Router

After syncing, models are available on your 9Router gateway (`http://127.0.0.1:20127/v1`):

| Model ID in 9Router | Upstream Model | Capabilities |
|---|---|---|
| `step/step-5-preview` | `step-5-preview` | Multimodal, Deep Reasoning, Thinking |
| `step/step-3.7-flash` | `step-3.7-flash` | Fast Reasoning, High-Throughput Agentic |
| `step/step-3.5-flash` | `step-3.5-flash` | Ultra-fast Coding & Tool Execution |

---

## 🔒 Security & Data Hygiene
* Private keys and sessions are stored strictly in `data/stepfun_keys.json` with `0600` permissions.
* `.gitignore` prevents token leaks to version control.
