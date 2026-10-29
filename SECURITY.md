# Security policy

OpenRun stores health data and holds Garmin sessions, so security reports are taken seriously.

## Supported versions

Only the latest release (and `main`) gets security fixes.

## Reporting a vulnerability

Please **do not open a public issue**. Report it privately through GitHub: *Security* tab › *Report a vulnerability* ([private vulnerability reporting](https://docs.github.com/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)).

Include what you found, how to reproduce it, and the impact you expect. You will get an answer within a week; once a fix is released the advisory is published with credit to you, unless you prefer otherwise.

## Scope

In scope: the OpenRun server and web app, the MCP server, the Docker image and the default configuration.

Out of scope: vulnerabilities in third-party services (Garmin, AI providers, push services) and setups that ignore the documented requirements (for example exposing OpenRun to the internet without HTTPS, or with `OPENRUN_TRUST_LOCAL=1` behind a proxy).

## Hardening notes for self-hosters

See the *Security* section of [docs/self-hosting.md](docs/self-hosting.md#security).
