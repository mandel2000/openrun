# Changelog

All notable changes to OpenRun are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.2.0] - 2026-10-29

### Added
- English and Spanish: the whole app (interface, workout titles and descriptions, notifications, analysis, race strategy and the AI coach's answers) follows each user's language, chosen in *Settings › Appearance and language* or taken from the browser. `OPENRUN_LANG` sets the default.
- Ko-fi donations: *Support OpenRun* in Settings, the GitHub Sponsor button and a section in the README.
- CI checks that every interface and server string has a Spanish translation.
- Demo mode (`OPENRUN_DEMO=1`): *Try the demo* on the sign-in screen opens a shared account with a generated half-marathon plan, ~10 months of runs with maps and charts, post-run analysis, wellness data and races; Garmin, the AI coach and account changes are off and the data is rebuilt daily.

### Changed
- Code, AI prompts and tool descriptions are in English; the daily routine log uses English step names.

### Fixed
- The sign-in prompt follows the browser language.
- Race strategy: the elevation axis fits the course (profiles no longer look flat) and the course chip is translated.

### Docs
- Screenshots and a link to the live demo in the README.

## [0.1.0] - 2026-10-29

First public release.

### Added
- Evidence-based training plans (5K, 10K, half, marathon, general fitness): periodisation, Daniels VDOT paces, ~80/20 intensity, capped progression with recovery weeks, taper, strength and mobility sessions.
- Garmin integration: activities, HRV, sleep and resting HR in; structured workouts with pace targets out to the Garmin Connect calendar; only changed workouts are pushed.
- File uploads (`.fit`, `.gpx`, `.tcx`) and full Strava/Garmin history imports, with maps, charts and splits for uploaded runs.
- Readiness score 0–100 (HRV, sleep, resting HR, training load and a daily check-in) with a proposal to soften today's session and an explanation from the coach.
- Plan adaptation: missed key sessions rescheduled without stacking hard days, late runs credited to the missed session, return-to-running after a break with re-paced workouts.
- Post-run analysis per interval and automatic pace recalibration; heat adjustment from the weather forecast.
- Race planning: A/B/C races fitted into the plan, race-day strategy with per-km pacing on the course profile, forecast heat and fuelling, race workout on the watch.
- Records, race predictions, training load (TRIMP, CTL/ATL, ACWR) and a weekly review.
- AI coach with tools on the athlete's data: in-app (Anthropic, NVIDIA, Gemini, Groq, OpenRouter, OpenAI, Ollama) or through the MCP server (Claude Desktop, Gemini CLI), with per-user daily limits.
- Multi-user accounts with invitation links, per-user data isolation, guided onboarding and personal API tokens for the MCP server.
- Installable web app with push notifications; drag and drop to move sessions.
- Self-hosting: Docker image for amd64/arm64, Docker Compose, `.env` configuration, deep health check, daily database snapshots, uptime workflow with optional ntfy alerts.

[Unreleased]: https://github.com/mandel2000/openrun/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/mandel2000/openrun/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/mandel2000/openrun/releases/tag/v0.1.0
