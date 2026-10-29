# 🏃 OpenRun

[![CI](https://github.com/mandel2000/openrun/actions/workflows/ci.yml/badge.svg)](https://github.com/mandel2000/openrun/actions/workflows/ci.yml)
[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE)
[![Ko-fi](https://img.shields.io/badge/support-Ko--fi-ff5e5b?logo=ko-fi&logoColor=white)](https://ko-fi.com/manueldelgado54792)

**An open-source, self-hosted running coach.** Evidence-based training plans, Garmin sync (data in, structured workouts out to your watch), HRV-guided readiness and an AI coach that works with your real data. A free alternative to subscription apps such as Runna.

[Leer en español](README.es.md) · [Self-hosting](docs/self-hosting.md) · [MCP (Claude Desktop, Gemini CLI)](docs/mcp.md) · [The science](docs/science.md) · [Contributing](CONTRIBUTING.md)

> Available in English and Spanish (each user picks it in *Settings*). More languages are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md#translations).

## Features

- **Training plans** for 5K, 10K, half, marathon and general fitness: periodisation (base → build → specific → taper), Daniels VDOT paces, ~80/20 intensity, ≤ 10 % weekly progression with recovery weeks, strength and mobility.
- **Garmin** (tested with a Forerunner 265): pulls activities, HRV, sleep and resting HR; pushes structured workouts with pace targets to the Garmin Connect calendar, which syncs to the watch.
- **No Garmin? No problem**: upload `.fit`, `.gpx` or `.tcx` files from any watch or app, or your whole Strava export. Uploaded runs get maps, charts and splits and count for the plan.
- **Readiness 0–100** from HRV, sleep, resting HR, training load (form/ACWR) and a two-tap daily check-in. When you are tired it proposes a softer version of today's session; you accept or keep the plan, and the coach explains why.
- **The plan adapts**: missed key sessions get a proposed slot later in the week (never next to another hard day), a run done a day late still counts, and "I've been off N days" (illness, injury, travel) eases you back and re-paces when needed.
- **Post-run analysis**: every interval against its target; when sessions consistently come out easier or harder, paces are recalibrated (like *Pace Insights*).
- **Heat adjustment**: forecast temperature and dew point at your usual training hour slow the pace targets.
- **Race strategy**: per-km pacing at even effort on the real course profile (GPX/TCX/KML or link), forecast heat on race day, fuelling plan, and a race workout on your watch.
- **Activities**: map, synced pace/HR/elevation charts, km splits and running dynamics.
- **Records and predictions** (1K to marathon), training load (TRIMP, CTL/ATL), weekly review with an AI comment.
- **AI coach** inside the app (NVIDIA or Gemini free tiers, Ollama locally, or Anthropic/OpenAI/Groq/OpenRouter APIs) or from **Claude Desktop / Gemini CLI via MCP** using your own subscription. Paces are always computed by the server from your VDOT, never by the model.
- **Multi-user** with invitation links: each person has their own plan, Garmin account, coach, data and personal MCP token. Per-user daily AI limits.
- **Installable web app (PWA)** with its own push notifications: today's session, post-run analysis, missed sessions, weekly review.
- Bluetooth heart-rate straps (e.g. Amazfit Helio Strap) for a morning HRV measurement from the browser; Zepp data import.

The reasoning and references behind each training rule are in [docs/science.md](docs/science.md).

## Quick start

### Docker (recommended)

```bash
git clone https://github.com/mandel2000/openrun.git && cd openrun
cp .env.example .env          # set OPENRUN_PASSWORD (12+ characters) and, optionally, an AI provider key
docker compose up -d
```

Open http://localhost:8000 and sign in as `admin` with that password. Data lives in the `openrun-data` volume.

### On your computer, without Docker

Requirements: Python ≥ 3.12 and Node ≥ 20.

```bash
./run.sh
```

Open http://localhost:8000 (requests from the same machine need no password). Data is stored in `~/.openrun/`. To keep it running and reach it from your phone, see [docs/self-hosting.md](docs/self-hosting.md#on-your-own-computer).

### On a server

Behind a reverse proxy with HTTPS (Caddy, Traefik, Coolify, …), multi-user, with notifications and your own domain: [docs/self-hosting.md](docs/self-hosting.md).

## First steps

1. **Sign in.** New users see a short setup: profile, data source (Garmin or files) and goal.
2. **Settings › Garmin**: log in (MFA supported) and sync your history. Or upload files in **Progress › Activities**.
3. **Plan**: goal, race date, days per week and a recent race time → *Generate plan*.
4. **Today**: the session of the day, the readiness check-in and any plan adjustments. Send the week to your watch.
5. **Settings › Notifications** on your phone (on iPhone, add the app to the Home Screen first).

## AI coach options

| Option | How | Cost |
|---|---|---|
| **Your Claude subscription** (Free/Pro/Max) | OpenRun as an MCP server in Claude Desktop ([docs/mcp.md](docs/mcp.md)) | No extra cost |
| **Gemini CLI** | Same MCP config in `~/.gemini/settings.json` | Free with a Google account |
| **NVIDIA** (in-app chat) | `OPENRUN_PROVIDER=nvidia`, `NVIDIA_API_KEY=nvapi-…` | Free NVIDIA Developer account, ~40 req/min, trial terms |
| **Gemini API** (in-app chat) | `OPENRUN_PROVIDER=gemini`, `GEMINI_API_KEY=…` | Free tier with limits; Google may use the data |
| **Ollama** (local) | `ollama pull qwen3:8b`, `OPENRUN_PROVIDER=ollama` | Free and private; weaker reasoning |
| **Paid APIs** | `ANTHROPIC_API_KEY`, or `OPENRUN_PROVIDER=openai\|groq\|openrouter` with its key | Pay per use |

Consumer subscriptions (Claude, ChatGPT, Gemini) do not include API access for third-party apps; MCP is the supported way to use them with your own data. All settings: [docs/configuration.md](docs/configuration.md).

## Documentation

| | |
|---|---|
| [Self-hosting](docs/self-hosting.md) | Local, Docker, server, phone, domain, notifications, monitoring, upgrades |
| [Configuration](docs/configuration.md) | Every environment variable |
| [MCP](docs/mcp.md) | Use the coach from Claude Desktop or Gemini CLI |
| [Integrations](docs/integrations.md) | Garmin, files and Strava, heart-rate straps, weather, race calendar |
| [Architecture](docs/architecture.md) | How the code is organised |
| [The science](docs/science.md) | What the plans are based on |
| [Español](docs/es/) | Guías en español |

## Limitations

- Garmin's API is unofficial (via [python-garminconnect](https://github.com/cyberjunky/python-garminconnect)); it can break if Garmin changes its login or endpoints.
- Web Bluetooth (HRV measurement in the browser) works in Chrome and Edge, not Safari or Firefox.

**Not medical advice.** If you feel pain or unusual symptoms, stop and see a professional.

## Contributing

Issues and pull requests are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) for the development setup, branch workflow and commit conventions, and [SECURITY.md](SECURITY.md) to report vulnerabilities privately.

## Support the project

OpenRun is free and built in spare time. If it helps your training, you can [buy me a coffee on Ko-fi](https://ko-fi.com/manueldelgado54792) ♥. Stars, bug reports and pull requests help too.

## License

[GNU Affero General Public License v3.0](LICENSE). You can use, modify and self-host OpenRun freely; if you run a modified version as a service for others, you must share your changes under the same license.

Built on [python-garminconnect](https://github.com/cyberjunky/python-garminconnect), [FastAPI](https://fastapi.tiangolo.com), [React](https://react.dev), [Open-Meteo](https://open-meteo.com), [OpenStreetMap](https://www.openstreetmap.org) and [Leaflet](https://leafletjs.com).
