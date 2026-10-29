# Self-hosting OpenRun

OpenRun is a single process (FastAPI API + the built React app) with a SQLite database. You can run it on your own computer or on a server; everything stays under your control.

- [On your own computer](#on-your-own-computer)
- [With Docker Compose](#with-docker-compose)
- [On a server with HTTPS](#on-a-server-with-https)
- [Users and invitations](#users-and-invitations)
- [Notifications](#notifications)
- [Monitoring](#monitoring)
- [Data, backups and upgrades](#data-backups-and-upgrades)
- [Security](#security)

Every setting is an environment variable: see [configuration.md](configuration.md).

## On your own computer

Requirements: Python ≥ 3.12 and Node ≥ 20.

```bash
cp .env.example .env    # optional: AI provider key, etc.
./run.sh                # http://localhost:8000
```

`run.sh` creates the Python virtualenv, builds the web app when its sources change and starts the server. Requests from the same machine are trusted (no password); data goes to `~/.openrun/`.

The **daily routine** (Garmin sync, analysis, pace and heat adjustments, readiness, pushing the next 7 days to the watch) only runs while the server is up, at 06:30 by default or as soon as it starts if that time has passed.

### Start automatically (macOS)

```bash
scripts/install-autostart.sh                          # this computer only
OPENRUN_PIN=<pin> scripts/install-autostart.sh --lan  # also from your phone on the same wifi
```

It registers a `launchd` agent (`~/Library/LaunchAgents/com.openrun.server.plist`, mode 600) that starts OpenRun at login and restarts it if it crashes; the log goes to `~/.openrun/server.log`. Run it again after changing settings. To remove it: `launchctl unload ~/Library/LaunchAgents/com.openrun.server.plist` and delete that file. On Linux, a systemd user service running `./run.sh` does the same.

### From your phone on the same network

```bash
OPENRUN_HOST=0.0.0.0 OPENRUN_PIN=<pin> ./run.sh
```

Open `http://<computer-ip>:8000` on the phone (shown in *Settings › OpenRun on your phone*), sign in as `admin` with the PIN and add it to the Home Screen. `run.sh` refuses to listen on the network without a PIN. To reach it away from home use a VPN such as Tailscale; do not open ports on your router.

## With Docker Compose

```bash
cp .env.example .env    # set OPENRUN_PASSWORD (12+ characters)
docker compose up -d    # http://localhost:8000
```

The compose file uses the published image `ghcr.io/mandel2000/openrun` (amd64 and arm64, so a Raspberry Pi 4/5 works). `docker compose build` builds it from your checkout instead; `OPENRUN_VERSION=0.1.0` pins a release and `OPENRUN_PORT` changes the host port.

Plain HTTP is fine on a trusted network. Anywhere else, put it behind HTTPS (next section): passwords and session cookies must not travel in clear text.

## On a server with HTTPS

On a server OpenRun runs 24/7, so the daily routine never misses a day, and it is reachable from anywhere. Any VPS with 512 MB of free RAM is enough.

1. Run the container (Docker Compose as above, or your platform's equivalent) with at least `OPENRUN_PASSWORD` and `OPENRUN_PUBLIC_URL=https://run.example.com`.
2. Point a DNS **A** record (`run.example.com → <server IP>`) at the server.
3. Put a reverse proxy with automatic certificates in front of port 8000.

Caddy, for example (`Caddyfile`):

```
run.example.com {
    reverse_proxy localhost:8000
}
```

**Coolify**: new resource → this Git repository (or the image) → *Dockerfile* build pack → port 8000 → environment variables → domain (Let's Encrypt is automatic) → persistent storage mounted at `/data`. Redeploy after a push with the *Redeploy* button, a GitHub webhook or the Coolify API.

The image already sets `OPENRUN_TRUST_LOCAL=0` (behind a proxy nothing counts as local) and `OPENRUN_TRUST_PROXY=1` (real client IP and HTTPS from the proxy headers). It runs as a non-root user (uid 1000) with a healthcheck on `/api/health`.

### Changing the domain

Add the new domain to the proxy, update `OPENRUN_PUBLIC_URL`, redeploy, and on each phone open the new address, sign in, add it to the Home Screen again and re-enable notifications (they are tied to the domain).

### Moving from your computer to a server

1. Stop OpenRun on the computer so nothing writes while you copy (`launchctl unload ~/Library/LaunchAgents/com.openrun.server.plist`).
2. Copy `~/.openrun/openrun.db` and `~/.openrun/garmin/` into the container's `/data` (owner uid 1000).
3. Start the container. Garmin stays connected with the copied tokens, which is better than logging in from a datacenter IP that Garmin may challenge.

Run **only one instance**: two would both run the daily routine and push every workout twice.

## Users and invitations

- The first start creates the admin account (`OPENRUN_ADMIN_USER`, default `admin`) with `OPENRUN_PASSWORD`. Change the password later in *Settings › Your account*.
- **Invite someone**: *Settings › Users › Create invitation*, then send the link (`https://…/#invitacion=…`). It works once and expires after 14 days. With `OPENRUN_OPEN_SIGNUP=1` anyone can sign up without a link.
- Each user has their own plan, workouts, activities, health data, races, coach chat, settings, Garmin account and MCP token. Every data table carries `user_id` and the filter is applied in the ORM ([architecture.md](architecture.md#multi-user)).
- New users get a guided setup (profile → Garmin or files → goal and plan).
- The AI provider and its key are shared; each user has a daily request limit (`OPENRUN_AI_DAILY_LIMIT`, editable per user in *Settings › Users*). Admins are unlimited unless you set a limit.
- Admins can delete accounts together with all their data.

## Notifications

Browser push (Web Push with VAPID keys generated into `/data/vapid.pem`), no third-party app. Each user enables them per device in *Settings › Notifications*:

- **iPhone**: iOS 16.4 or later, with the app added to the Home Screen from Safari and opened from its icon.
- **Android and desktop**: Chrome, Edge or Firefox.

They cover today's session, post-run analysis (the server checks Garmin every ~2 h between 9:00 and 22:00), missed key sessions, the Monday weekly review and "Garmin disconnected". Each kind can be turned off. Admins also get a push if the daily database backup fails.

## Monitoring

- `GET /api/health` always answers `{"ok": true}` while the process is up (used by the container healthcheck).
- `GET /api/health?deep=1` also checks the database, that the background scheduler is still ticking and that the last backup succeeded. Any problem answers **503** with a list.
- The repository includes `.github/workflows/uptime.yml`, which calls the deep check every hour. In your fork, set the repository secret `OPENRUN_URL` to your address; a failed run makes GitHub email you. For a phone alert, install the **ntfy** app, subscribe to a long random topic name and store it as the secret `NTFY_TOPIC`. Without `OPENRUN_URL` the workflow does nothing.

## Data, backups and upgrades

Everything lives in the data folder (`/data` in the container, `~/.openrun/` locally):

| Path | Content |
|---|---|
| `openrun.db` | SQLite database (WAL mode) |
| `backups/` | Daily snapshot of the database, last 14 days |
| `garmin/` | Garmin session tokens of the admin; `garmin/users/<id>/` for other users |
| `secret.key` | Key that signs sessions (generated) |
| `vapid.pem` | Push notification key (generated; if deleted, every device has to re-enable notifications) |

The daily snapshots protect against mistakes, not against losing the disk: copy the data folder somewhere else if your data matters to you.

**Upgrading**: `docker compose pull && docker compose up -d` (or `git pull` and restart `run.sh`). Database migrations run automatically on start, and the first start after a structural migration keeps a full copy of the old database next to it.

**SQLite or Postgres?** SQLite in the volume is enough for a household or a group of friends: zero maintenance and no extra RAM. For more, set `OPENRUN_DATABASE_URL` (e.g. `postgresql+psycopg://…`) and add the `psycopg[binary]` driver to the image.

## Security

- The whole API requires a session (username and password) or an API token; only `/api/health`, login and invitation sign-up are public.
- Passwords are hashed with scrypt. Sessions are HMAC-signed, expire after 90 days and are bound to the password: changing it signs out every other device.
- Personal API tokens are random 256-bit values stored as SHA-256 hashes; regenerating or revoking one invalidates the old one.
- At most 10 failed attempts (login or invitation codes) per real client IP every 10 minutes.
- Importing a course by URL only fetches `https://` from public addresses, at most 8 MB. Push notifications are only sent to the Google, Mozilla, Apple and Microsoft push services.
- `Secure` + `HttpOnly` cookies, HSTS and anti-clickjacking headers.

Found a vulnerability? See [SECURITY.md](../SECURITY.md).
