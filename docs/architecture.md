# Architecture

One Python process serves the API and the built web app. A background thread runs the daily routine. Data is in SQLite (or any SQLAlchemy database).

```
browser / PWA ──HTTP──► FastAPI (backend/app/main.py) ──► services.py ──► training/ (pure rules)
                              │                              │
MCP client ──stdio──► mcp_server.py ──(local DB or HTTPS)────┘          integrations/ (Garmin, files, weather…)
                                                                         ai/coach.py (LLM providers + tools)
scheduler.py (thread): daily routine, intraday sync, backups ─► services.py
```

## Backend (`backend/app/`)

| Module | Role |
|---|---|
| `main.py` | FastAPI app: auth middleware, all `/api/*` endpoints, serves `frontend/dist` |
| `services.py` | Use cases: plans, workouts, sync, readiness, replanning, races, reviews, notifications. Endpoints, the scheduler and the coach tools all go through it |
| `training/` | Pure, unit-tested training rules: `vdot.py` (Daniels), `plan.py` (plan generator), `workouts.py` (session library), `load.py` (TRIMP, CTL/ATL, readiness), `adapt.py` (readiness adjustments), `replan.py` (missed sessions, breaks), `analysis.py` (post-run analysis, pace insights), `heat.py`, `race_plan.py` (race strategy), `records.py` (PRs, predictions), `strength.py` |
| `integrations/` | `garmin.py` (python-garminconnect, one session per user), `history_import.py` (FIT/GPX/TCX/Strava), `zepp.py`, `orycron.py` (race calendar) |
| `ai/coach.py` | System prompt, tool definitions and the tool loop for Anthropic and OpenAI-compatible providers; `run_tool()` is shared with the MCP server |
| `mcp_server.py` | MCP stdio server: same tools, run against the local database or a remote server's `/api/tools/*` |
| `db.py` | SQLModel tables and lightweight migrations (new nullable columns are added on start) |
| `tenancy.py` | Per-user data isolation (below) |
| `auth.py` | Passwords (scrypt), signed sessions, personal API tokens, rate limiting |
| `scheduler.py` | Per-user daily routine, intraday sync, daily backup, health state |
| `push.py` | Web Push (VAPID) |
| `i18n.py`, `locales/` | Server-side translations: `_()` picks the current user's language ([CONTRIBUTING.md](../CONTRIBUTING.md#translations)) |

### Multi-user

Every data table carries `user_id`. The current user lives in a context variable set by the auth middleware (web requests) or `as_user()` (scheduler, background jobs, MCP). Two SQLAlchemy hooks do the rest: SELECTs on tenant tables get `WHERE user_id = <current>` added, and new rows get the current `user_id` on flush. Without a current user, touching a tenant table raises, so data never leaks across accounts by accident. Code that really needs every user's rows passes `execution_options(all_users=True)`.

### Daily routine

At each user's sync time (06:30 by default): Garmin sync → post-run analysis → missed sessions → pace insights → weekly review (Mondays) → heat adjustment → readiness adjustment → push changed workouts for the next 7 days → morning notification. Each step is logged and failures don't stop the others. Between 9:00 and 22:00 a lighter sync every ~2 h picks up new runs and notifies their analysis.

### The coach never computes paces

The model chooses *what* to do (a 6×800 m session, move the long run…); the server turns it into paces from the athlete's VDOT and checks it against the plan rules. This keeps advice consistent across providers and safe with small models.

## Frontend (`frontend/src/`)

React + TypeScript + Vite, no UI framework. `pages/` are the six tabs (Today, Plan, Races, Progress, Coach, Settings); `components/` the shared pieces; `api.ts` the typed API client; `i18n.ts` + `locales/` the translations (`t()`); `index.css` the design tokens (light and dark). Charts use Recharts, maps Leaflet. The service worker (`public/sw.js`) only handles push notifications.

## Tests

`backend/tests/` covers the training rules, imports, the plan and readiness adaptations, multi-user isolation, auth, the coach tool loop and the MCP endpoints. Run `pytest` in `backend/`; CI also runs `ruff` and builds the frontend.
