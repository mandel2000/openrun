# Configuration

OpenRun is configured with environment variables. Copy [`.env.example`](../.env.example) to `.env`: `docker compose` and `./run.sh` both read it. Empty values count as unset. Everything else (training days, sync time, notifications, heat adjustment, location, …) is set per user inside the app.

## Access

| Variable | Default | Description |
|---|---|---|
| `OPENRUN_PASSWORD` | – | **Required on a server.** Initial password of the admin account, 12+ characters (the server refuses to start with a shorter one). Only used to create the account; change it later in *Settings › Your account*. `OPENRUN_PIN` is an older alias. |
| `OPENRUN_ADMIN_USER` | `admin` | Username of the admin account, created on first start. |
| `OPENRUN_OPEN_SIGNUP` | `0` | `1` lets anyone sign up; `0` requires an invitation link. |
| `OPENRUN_PUBLIC_URL` | – | Public address on a server (`https://run.example.com`). Shown in Settings and used for the MCP configuration. |
| `OPENRUN_API_TOKEN` | – | Server-wide bearer token (32+ characters) that acts as the admin. Optional: every user can create a personal token in *Settings › Coach*. |
| `OPENRUN_TRUST_LOCAL` | `1` (`0` in the image) | Trust requests from the same machine without a password. Must be `0` behind a reverse proxy. |
| `OPENRUN_TRUST_PROXY` | `0` (`1` in the image) | Read the client IP and scheme from `X-Forwarded-*` headers. Only behind a proxy you control. |
| `OPENRUN_SECRET` | generated | Key that signs sessions. By default a random key is stored in `<data>/secret.key`. |

## AI coach

| Variable | Default | Description |
|---|---|---|
| `OPENRUN_PROVIDER` | `anthropic` | `anthropic`, `nvidia`, `gemini`, `groq`, `openrouter`, `openai` or `ollama`. |
| `ANTHROPIC_API_KEY`, `NVIDIA_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `OPENAI_API_KEY` | – | Key of the chosen provider. |
| `OPENRUN_MODEL` | per provider | Model name. Defaults: Anthropic `claude-opus-5-5`, NVIDIA `minimaxai/minimax-m3.1-flash`, Gemini `gemini-flash-latest`, Groq `openai/gpt-oss-120b`, OpenRouter `openai/gpt-oss-120b:free`, OpenAI `gpt-5-mini`, Ollama `qwen3:8b`. |
| `OPENRUN_MODEL_FALLBACKS` | – | Comma-separated models to try when the main one fails or is saturated. |
| `OPENRUN_EFFORT` | `medium` | Thinking effort for Anthropic models (`low` is faster and cheaper). |
| `OPENRUN_REASONING_EFFORT` | `low` on NVIDIA | Reasoning effort for OpenAI-compatible models that support it. |
| `OPENRUN_BASE_URL`, `OPENRUN_API_KEY` | – | Any other OpenAI-compatible endpoint. |
| `OPENRUN_AI_DAILY_LIMIT` | `40` | AI requests per user per day (chat messages, weekly review, readiness explanations). Admins are unlimited unless a limit is set per user in *Settings › Users*. |

## Storage and runtime

| Variable | Default | Description |
|---|---|---|
| `OPENRUN_DATA` | `~/.openrun` (`/data` in the image) | Data folder: secret key, VAPID key, backups. |
| `OPENRUN_DB` | `<data>/openrun.db` | SQLite database file. |
| `OPENRUN_DATABASE_URL` | – | External database instead of SQLite, e.g. `postgresql+psycopg://user:pass@host:5432/openrun` (install the driver). |
| `OPENRUN_GARMIN_TOKENS` | `<data>/garmin` | Garmin session tokens. |
| `OPENRUN_SCHEDULER` | `1` | `0` disables the background scheduler (daily routine, intraday sync, backups). |
| `OPENRUN_VAPID_SUB` | `mailto:openrun@users.noreply.github.com` | Contact sent to the browser push services. |
| `TZ` | `Europe/Madrid` in the image | Time zone of the daily routine and dates. |
| `PORT` | `8000` | HTTP port. |

## Local network (`./run.sh`)

| Variable | Default | Description |
|---|---|---|
| `OPENRUN_HOST` | `127.0.0.1` | `0.0.0.0` makes the app reachable from other devices; then a password/PIN is required. |

## MCP server (`python -m app.mcp_server`)

| Variable | Default | Description |
|---|---|---|
| `OPENRUN_URL` | – | Address of an OpenRun server. Without it, the MCP server works directly on the local database. |
| `OPENRUN_API_TOKEN` | – | Your personal token (*Settings › Coach › Outside the app (MCP)*). |
| `OPENRUN_USER_ID` | `1` | Local mode only: which user's data to use. |
| `OPENRUN_IMAGE` | `ghcr.io/mandel2000/openrun:latest` | Image shown in the Docker-based MCP snippet in Settings. |
