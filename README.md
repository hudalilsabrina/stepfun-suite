# StepFun Suite (Step Plan & AI Studio 1M Relay)

Reverse-engineered autonomous registration, Tencent TCaptcha slider puzzle bypass, Outbound CLI OAuth device login, and OpenAI-compatible Web-to-API Relay Daemon for **StepFun AI (阶跃星辰)**.

---

## ⚡ Architecture & How It Works

StepFun maintains three layers of access:
1. **Standard OpenAPI (`api.stepfun.ai/v1`)**: Requires prepaid balances.
2. **Step Plan Gateway (`api.stepfun.ai/step_plan/v1`)**: Subscription harness (requires paid seat or voucher code).
3. **AI Studio Web Engine (`studio.stepfun.ai`)**: **Free unlimited tier with 1,000,000 (1M) context window & native thinking reasoning (`step-5-preview`)**!

```
+-------------------------------------------------------------------------------+
|                             STEPFUN SUITE RUNNER                              |
+-------------------------------------------------------------------------------+
       |                                                               |
  1. Auto-Register                                              2. Relay Server
       |                                                               |
       v                                                               v
[Tempik Disposable Email]                                    [HTTP Daemon :8795/v1]
       +                                                               +
[Tencent TCaptcha 5-Filter Solver]                                     |
       +                                                     [Round-Robin Multi-Session]
[Playwright Headless Browser]                                          |
       |                                                               v
       v                                                [AI Studio SSE Stream Relay]
[Account Created & Saved in Pool]                                      +
       |                                                [Passport Token Auto-Refresh]
       v                                                               |
[9Router SQLite Gateway (:20127)] <------------------------------------+
       |
       v
[Hermes Agent / Any OpenAI Client] (Full 1M Context Window)
```

---

## 🛠️ Features

- 🤖 **Autonomous Registration (`main.py auto`)**:
  - Automatically provisions disposable inboxes via Tempik Cloudflare Worker (`mail.xentranetwork.me`).
  - Solves Tencent TCaptcha slider puzzle via computer vision (NCC, Canny, Otsu, Sobel dark edge detection).
  - Fetches OTP, accepts terms, logs in, and registers the session.
- 🔄 **AI Studio 1M Token Relay Daemon (`server.py`)**:
  - Translates standard OpenAI `/v1/chat/completions` into StepFun AI Studio SSE stream events.
  - Exposes `step-5-preview` (1M context window) and `step-3.5-flash` (256K context window).
  - Auto-refreshes JWT access tokens via `PassportService/RefreshToken` before expiration.
  - Multi-account round-robin pool rotation.
- 🎟️ **Voucher Redemption (`main.py redeem`)**:
  - Direct ConnectRPC call to `UseVoucherCode` on StepFun DevCenter.
- 🌐 **9Router Gateway Integration (`router_sync.py`)**:
  - Injects model mappings and proxy rules directly into 9Router SQLite (`/var/lib/9router/db/data.sqlite`).

---

## 🚀 Quick Usage

### 1. Harvest a New Account Automatically
```bash
python3 main.py auto --region oversea
```
*Time taken: ~30 seconds per account.*

### 2. Run the Relay Daemon (Systemd)
The relay runs as a system service in the background:
```bash
# Check status
systemctl status stepfun-relay.service

# Restart after adding new accounts
systemctl restart stepfun-relay.service
```

### 3. Call via Local Relay Directly (:8795)
```bash
curl -X POST http://127.0.0.1:8795/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "step-5-preview",
    "messages": [{"role": "user", "content": "Hello!"}],
    "max_tokens": 1024
  }'
```

### 4. Call via 9Router Gateway (:20127)
```bash
curl -X POST http://127.0.0.1:20127/v1/chat/completions \
  -H "Authorization: Bearer <9ROUTER_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "step/step-5-preview",
    "messages": [{"role": "user", "content": "Sebutkan 3 planet terdekat dari matahari."}]
  }'
```

---

## 🧩 Supported Models in 9Router

| Model ID in 9Router | Upstream Model | Context Window | Capabilities |
|---|---|---|---|
| `step/step-5-preview` | `step-5-preview` | **1,000,000 (1M)** | Multimodal, Deep Thinking Reasoning |
| `step/step-3.7-flash` | `step-3.7-flash` | 262,144 (256K) | Fast Reasoning, High-Throughput |
| `step/step-3.5-flash` | `step-3.5-flash` | 262,144 (256K) | Ultra-fast Coding & Tool Execution |

---

## 🔒 Security
- All sensitive credentials and tokens are stored in `data/stepfun_keys.json` with `.gitignore` exclusion.
