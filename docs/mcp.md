# Using the coach from Claude Desktop or Gemini CLI (MCP)

OpenRun ships a [Model Context Protocol](https://modelcontextprotocol.io) server. Connect it to an MCP client and chat with your coach there, with your own subscription (Claude Free/Pro/Max) or for free (Gemini CLI with a Google account): no API key for OpenRun needed.

The MCP server exposes the same tools and evidence-based rules as the in-app coach. The client's model does the talking; OpenRun computes paces, plans and adjustments. What the coach changes (new workouts, moved sessions, race adjustments) appears in the app and is pushed to your watch.

## Get your token (OpenRun on a server)

In OpenRun: *Settings › Coach › Outside the app (MCP)* › **Generate token**. The token gives access to **your** data only, is shown once, and can be regenerated or revoked there. The same screen prints a ready-to-paste configuration with your server address and token.

## Option A: Docker (nothing else to install)

```json
{
  "mcpServers": {
    "openrun": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "-e", "OPENRUN_URL", "-e", "OPENRUN_API_TOKEN",
               "ghcr.io/mandel2000/openrun:latest", "python", "-m", "app.mcp_server"],
      "env": { "OPENRUN_URL": "https://run.example.com", "OPENRUN_API_TOKEN": "or_…" }
    }
  }
}
```

Docker Desktop (or Docker Engine) must be running when the client starts.

## Option B: from a clone of this repository

```bash
git clone https://github.com/mandel2000/openrun.git
cd openrun/backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

```json
{
  "mcpServers": {
    "openrun": {
      "command": "/path/to/openrun/backend/.venv/bin/python",
      "args": ["-m", "app.mcp_server"],
      "env": { "PYTHONPATH": "/path/to/openrun/backend",
               "OPENRUN_URL": "https://run.example.com", "OPENRUN_API_TOKEN": "or_…" }
    }
  }
}
```

## Option C: OpenRun on the same computer

When OpenRun runs locally (`./run.sh`), leave out `OPENRUN_URL` and the token: the MCP server works directly on the local database (`~/.openrun/openrun.db`). *Settings › Coach* shows the exact paths. `OPENRUN_USER_ID` selects another user than the admin.

## Where to paste it

- **Claude Desktop**: *Settings › Developer › Edit Config* (`claude_desktop_config.json`), then restart Claude Desktop. OpenRun appears in the tools menu of a new chat.
- **Gemini CLI**: the same `mcpServers` block in `~/.gemini/settings.json`.
- **Any other MCP client** that supports stdio servers: same command, arguments and environment.

## Tools

| Area | Tools |
|---|---|
| Athlete | `get_athlete_profile`, `update_athlete_profile`, `calculate_vdot` |
| Plan and workouts | `get_plan_overview`, `get_workouts`, `generate_plan`, `create_workout`, `move_workout`, `delete_workout`, `add_extra_run`, `push_to_garmin` |
| Activities and fitness | `get_recent_activities`, `get_training_load`, `get_personal_records`, `get_race_predictions` |
| Readiness and adaptation | `get_readiness`, `adapt_today_to_readiness`, `not_feeling_100`, `get_missed_sessions`, `reschedule_missed`, `report_break` |
| Races | `list_races`, `add_race`, `delete_race`, `get_race_strategy`, `search_race_calendar` |

Tools that replace the plan, add races or report a break tell the model to confirm with you first.

## Troubleshooting

- **401 / "Error conectando con OpenRun"**: the token was regenerated or revoked, or `OPENRUN_URL` is wrong (no trailing path, `https://`).
- **Nothing appears in Claude Desktop**: check the JSON is valid and restart the app; Claude Desktop's MCP log shows the server's errors.
- **Docker option is slow the first time**: the image is downloaded once (~500 MB).
