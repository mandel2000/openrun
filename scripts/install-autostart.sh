#!/usr/bin/env bash
# Start OpenRun automatically at login (macOS launchd), so the 06:30 routine runs every day.
# Usage: scripts/install-autostart.sh            (local only)
#        OPENRUN_PIN=<pin> scripts/install-autostart.sh --lan   (also on your wifi)
# Remove: launchctl unload ~/Library/LaunchAgents/com.openrun.server.plist && rm that file
# Full guide: docs/self-hosting.md (English) or docs/es/arranque-y-movil.md (Spanish)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/com.openrun.server.plist"
HOST=127.0.0.1
if [ "${1:-}" = "--lan" ]; then
  HOST=0.0.0.0
  : "${OPENRUN_PIN:?Define OPENRUN_PIN para el modo --lan}"
fi
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/.openrun"
# launchd has a minimal PATH: include where python3 and node/npm live (e.g. nvm)
EXTRA_PATH=""
for bin in python3 npm; do
  d="$(dirname "$(command -v "$bin" 2>/dev/null || echo /usr/bin/x)")"
  EXTRA_PATH="$EXTRA_PATH$d:"
done
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.openrun.server</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$ROOT/run.sh</string></array>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>${EXTRA_PATH}/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>OPENRUN_HOST</key><string>$HOST</string>
    <key>OPENRUN_PIN</key><string>${OPENRUN_PIN:-}</string>
    <key>ANTHROPIC_API_KEY</key><string>${ANTHROPIC_API_KEY:-}</string>
    <key>OPENRUN_PROVIDER</key><string>${OPENRUN_PROVIDER:-anthropic}</string>
    <key>GEMINI_API_KEY</key><string>${GEMINI_API_KEY:-}</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$HOME/.openrun/server.log</string>
  <key>StandardErrorPath</key><string>$HOME/.openrun/server.log</string>
</dict></plist>
PL
chmod 600 "$PLIST"
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "OpenRun arrancará solo al iniciar sesión (log: ~/.openrun/server.log)."
