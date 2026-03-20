# Connecting the Next.js Frontend to the Python Backend

This guide explains how to wire up the Next.js frontend (`localhost:6002`) to the
FastAPI Python backend (`localhost:8000`).

---

## Architecture Options

### Option A: Proxy (Recommended for production)

```
┌─────────────────────────────────────┐
│  Browser                            │
│  ┌─────────────────────────────┐    │
│  │  Next.js Frontend           │    │
│  │  (localhost:6002)           │    │
│  │  /api/* ──rewrites──┐      │    │
│  └──────────────────────┼──────┘    │
│                         ▼           │
│  ┌─────────────────────────────┐    │
│  │  Python Backend (FastAPI)   │    │
│  │  (localhost:8000)           │    │
│  └─────────────────────────────┘    │
└─────────────────────────────────────┘
No CORS needed. Set PYTHON_API_URL=http://localhost:8000
```

The `next.config.ts` rewrite rule forwards every `/api/*` request from the
Next.js server process to the Python backend. The browser never makes a
cross-origin request, so CORS configuration on the Python side is not required.

### Option B: Direct (For development or separate deployments)

```
┌─────────────────────────────────────┐
│  Browser                            │
│  ┌──────────────┐  ┌────────────┐   │
│  │  Next.js      │  │  Python    │   │
│  │  Frontend     │──│  Backend   │   │
│  │  :6002        │  │  :8000     │   │
│  └──────────────┘  └────────────┘   │
└─────────────────────────────────────┘
Needs CORS. Set NEXT_PUBLIC_PYTHON_API_URL=http://localhost:8000
```

The browser calls the Python backend directly. CORS headers must be configured
on the Python side to allow the frontend origin.

---

## Quick Start

### Option A: Proxy

1. Start the Python backend:
   ```bash
   cd backend
   pip install -e .
   uvicorn app.main:app --port 8000 --reload
   ```

2. Add to the frontend `.env.local` (create the file in the repo root if it does
   not exist):
   ```
   PYTHON_API_URL=http://localhost:8000
   ```

3. Start the Next.js frontend:
   ```bash
   npm run dev
   ```

4. Open http://localhost:6002

The frontend's Next.js server proxies every `/api/*` call to the Python backend
transparently. No CORS configuration is needed.

### Option B: Direct

1. Start the Python backend:
   ```bash
   cd backend
   pip install -e .
   uvicorn app.main:app --port 8000 --reload
   ```

2. Add to the frontend `.env.local`:
   ```
   NEXT_PUBLIC_PYTHON_API_URL=http://localhost:8000
   ```

3. Add to the backend `.env` (create the file in `backend/` if it does not
   exist):
   ```
   ALLOWED_ORIGINS=http://localhost:6002
   ```

4. Start the Next.js frontend:
   ```bash
   npm run dev
   ```

5. Open http://localhost:6002

---

## Environment Variables

### Frontend (`<repo-root>/.env.local`)

| Variable | Used by | Purpose |
|---|---|---|
| `PYTHON_API_URL` | Next.js server (build-time + runtime) | Enables the `/api/*` proxy rewrite in `next.config.ts`. **Option A only.** |
| `NEXT_PUBLIC_PYTHON_API_URL` | Browser JavaScript | Direct URL for client-side fetch calls. **Option B only.** |
| `NEXT_PUBLIC_BASE_PATH` | Next.js | Sub-directory prefix (e.g. `/nextaidrawio`) for reverse-proxy deployments. |

> Only one of `PYTHON_API_URL` / `NEXT_PUBLIC_PYTHON_API_URL` should be set at
> a time. Setting both can cause requests to be routed twice.

### Backend (`backend/.env`)

| Variable | Default | Purpose |
|---|---|---|
| `AI_PROVIDER` | `bedrock` | LLM provider (`openai`, `anthropic`, `google`, `ollama`, etc.). |
| `AI_MODEL` | `global.anthropic.claude-sonnet-4-5-20250929-v1:0` | Model identifier for the chosen provider. |
| `ALLOWED_ORIGINS` | `*` | Comma-separated CORS origins, or `*` to allow all. **Set this for Option B.** |
| `ACCESS_CODE_LIST` | _(unset)_ | Comma-separated valid access codes. Requests must supply the code in `x-access-code`. |
| `ALLOW_PRIVATE_URLS` | `true` | Set `false` to block SSRF attacks against internal addresses. |
| `ENABLE_VLM_VALIDATION` | `true` | Enable Vision-Language Model post-generation diagram validation. |
| `DYNAMODB_QUOTA_TABLE` | _(unset)_ | DynamoDB table name for quota tracking; quota is disabled when unset. |
| `LANGFUSE_PUBLIC_KEY` | _(unset)_ | Langfuse public key for LLM tracing; telemetry disabled when unset. |
| `LANGFUSE_SECRET_KEY` | _(unset)_ | Langfuse secret key. |
| `LANGFUSE_BASEURL` | _(unset)_ | Langfuse ingestion endpoint (e.g. `https://cloud.langfuse.com`). |
| `MAX_OUTPUT_TOKENS` | `16384` | Maximum tokens the LLM may generate per response. |
| `MAX_TOOL_STEPS` | `5` | Maximum agentic tool-call steps per request. |
| `MAX_FILE_SIZE_BYTES` | `2097152` | Maximum uploaded file size in bytes (2 MB). |
| `MAX_FILES_PER_MESSAGE` | `5` | Maximum file attachments per message. |
| `DIAGRAM_EXPORT_TIMEOUT_SECONDS` | `10.0` | Timeout for PPTX/PNG export operations. |

See `backend/.env.example` for the full list, including provider-specific API
keys (OpenAI, Anthropic, Google, AWS Bedrock, Azure, Ollama, etc.).

---

## API Compatibility Matrix

All routes are registered under the `/api` prefix by `app/main.py`.

| Endpoint | Method | Protocol | Proxy (A) | Direct (B) | Notes |
|---|---|---|---|---|---|
| `/health` | GET | JSON | ✅ | ✅ | Liveness probe; no `/api` prefix. |
| `/api/config` | GET | JSON | ✅ | ✅ | Returns server limits and feature flags. |
| `/api/chat` | POST | SSE (`text/event-stream`) | ✅ | ✅ | Main streaming diagram-generation endpoint. Events: `data: {...}\n\n` or `data: [DONE]\n\n`. |
| `/api/validate-diagram` | POST | Text stream (JSON) | ✅ | ✅ | VLM diagram validation; response is a streamed JSON object parsed by the AI SDK `useObject` hook. |
| `/api/validate-model` | POST | JSON | ✅ | ✅ | Test AI provider credentials with a lightweight completion. |
| `/api/export-pptx` | POST | Binary download | ✅ | ✅ | Returns raw PPTX bytes with `Content-Disposition: attachment`. |
| `/api/parse-url` | POST | JSON | ✅ | ✅ | Fetches a URL and returns article text as Markdown. |
| `/api/server-models` | GET | JSON | ✅ | ✅ | Returns server-configured AI model list for the model picker. |
| `/api/verify-access-code` | POST | JSON | ✅ | ✅ | Validates the `x-access-code` request header. |
| `/api/log-feedback` | POST | JSON | ✅ | ✅ | Records thumbs-up/down in Langfuse (no-op when Langfuse is unconfigured). |
| `/api/log-save` | POST | JSON | ✅ | ✅ | Records a diagram-save event in Langfuse (no-op when unconfigured). |

### SSE event format for `/api/chat`

Each line in the stream is a standard SSE data event:

```
data: {"type": "tool_call", "name": "display_diagram", "arguments": {"xml": "..."}}\n\n
data: {"type": "text", "text": "Here is your diagram."}\n\n
data: [DONE]\n\n
```

The stream carries `X-Accel-Buffering: no` and `Cache-Control: no-cache` headers
to prevent nginx/CDN buffering.

### Optional request headers for `/api/chat`

| Header | Purpose |
|---|---|
| `x-access-code` | Access code when `ACCESS_CODE_LIST` is configured. |
| `x-provider` | Override the server's default AI provider. |
| `x-model-id` | Override the server's default model. |
| `x-api-key` | Bring-your-own API key (bypasses quota check). |
| `x-base-url` | Custom provider base URL. |
| `x-minimal-style` | `"true"` to request minimal diagram styling. |
| `x-aws-access-key-id` | AWS credentials for Bedrock override. |
| `x-aws-secret-access-key` | AWS credentials for Bedrock override. |
| `x-aws-region` | AWS region for Bedrock override. |
| `x-aws-session-token` | Optional AWS session token. |
| `x-vertex-api-key` | Google Vertex AI Express Mode key. |

---

## Troubleshooting

### CORS errors in the browser console

**Symptom:** `Access-Control-Allow-Origin` missing or mismatched.

**Cause:** You are using Option B (direct) but `ALLOWED_ORIGINS` on the backend
does not include the frontend origin.

**Fix:**
```bash
# backend/.env
ALLOWED_ORIGINS=http://localhost:6002
```

Restart the backend after changing `.env`. The wildcard `*` is the default and
works for open development, but credentials (cookies) cannot be sent with
wildcard origins.

---

### 502 Bad Gateway

**Symptom:** All `/api/*` calls return HTTP 502 when using Option A.

**Cause:** `PYTHON_API_URL` is set but the Python backend is not running or is
not reachable at that URL.

**Fix:** Confirm the backend is running:
```bash
curl http://localhost:8000/health
# Expected: {"status": "ok"}
```

---

### Streaming responses arrive all at once instead of incrementally

**Symptom:** The chat response appears only after the entire generation is
complete, not token-by-token.

**Causes and fixes:**

1. **nginx buffering** — Add to your nginx location block:
   ```
   proxy_buffering off;
   proxy_cache off;
   ```
   Or ensure the backend's `X-Accel-Buffering: no` header is honoured.

2. **Cloudflare or CDN** — Disable response buffering for `/api/chat`.

3. **Node.js fetch** — If you are making a custom fetch call, make sure you are
   reading `response.body` as a `ReadableStream`, not awaiting `response.json()`.

---

### 401 Unauthorized

**Symptom:** All API calls return `{"error": "Invalid or missing access code..."}`.

**Cause:** `ACCESS_CODE_LIST` is set on the backend and the frontend is not
sending the `x-access-code` header.

**Fix:** Either remove `ACCESS_CODE_LIST` from the backend `.env` for local
development, or configure the frontend to send the access code in Settings.

---

### 503 Service Unavailable on `/api/export-pptx`

**Symptom:** PPTX export returns HTTP 503.

**Cause:** The `drawio2pptx` optional dependency is not installed.

**Fix:**
```bash
cd backend
pip install drawio2pptx
```

---

### VLM validation always returns `valid: true`

**Symptom:** Diagram validation never reports issues.

**Cause:** `ENABLE_VLM_VALIDATION=false` is set, or the configured model does
not support vision inputs.

**Fix:** Set `ENABLE_VLM_VALIDATION=true` and ensure `AI_MODEL` (or
`VALIDATION_MODEL`) is a vision-capable model (e.g. `gpt-4o`,
`claude-3-5-sonnet`, `gemini-2.0-flash`).

---

## Development Convenience Script

To start both servers in a single terminal session:

```bash
bash backend/scripts/start_dev.sh
```

Press `Ctrl+C` to stop both processes.

To run the connection test suite against a running backend:

```bash
python backend/scripts/test_connection.py
# Override the backend URL if needed:
BACKEND_URL=http://localhost:8000 python backend/scripts/test_connection.py
```
