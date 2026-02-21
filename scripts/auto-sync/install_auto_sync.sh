#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LABEL="com.loup.ai-tools.sync"
PLIST_PATH="${HOME}/Library/LaunchAgents/${LABEL}.plist"
WATCHEXEC="/opt/homebrew/bin/watchexec"
PYTHON="/opt/homebrew/bin/python3"

if [ ! -x "$PYTHON" ]; then
  PYTHON="/usr/bin/python3"
fi

if [ ! -x "$PYTHON" ]; then
  cat <<'MSG' >&2
Python 3 not found. Install it, then re-run this script.
Recommended: brew install python
MSG
  exit 1
fi

if [ -x /opt/homebrew/bin/brew ]; then
  if [ ! -x "$WATCHEXEC" ]; then
    /opt/homebrew/bin/brew install watchexec
  fi
else
  if [ ! -x "$WATCHEXEC" ]; then
    echo "watchexec not found at ${WATCHEXEC}. Install with: brew install watchexec" >&2
    exit 1
  fi
fi

VENV_DIR="${ROOT}/scripts/.venv"
"$PYTHON" -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install -r "${ROOT}/scripts/client-sync/requirements.txt"

/bin/chmod +x "${ROOT}/scripts/auto-sync/watch_ai_sync.sh"
/bin/chmod +x "${ROOT}/scripts/auto-sync/notify_sync.sh"
/bin/chmod +x "${ROOT}/scripts/shared/check_client_versions.py"
/bin/chmod +x "${ROOT}/scripts/shared/sync_summary.py"

VERSION_LOCK="${ROOT}/scripts/.client-versions.json"
if [ ! -f "$VERSION_LOCK" ]; then
  echo "Missing ${VERSION_LOCK}. This repo is version-bound; do not generate it locally." >&2
  echo "Pull the file from the repo, then re-run this installer." >&2
  exit 1
fi
if ! "$VENV_DIR/bin/python3" "${ROOT}/scripts/shared/check_client_versions.py" --check "$VERSION_LOCK" >/dev/null; then
  echo "Client version mismatch detected. Refusing to continue." >&2
  echo "Run ${ROOT}/scripts/shared/check_client_versions.py --check ${VERSION_LOCK} for details." >&2
  exit 1
fi

cat <<PLIST > "$PLIST_PATH"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>${LABEL}</string>

    <key>ProgramArguments</key>
    <array>
      <string>${ROOT}/scripts/auto-sync/watch_ai_sync.sh</string>
    </array>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>WorkingDirectory</key>
    <string>${ROOT}</string>

    <key>StandardOutPath</key>
    <string>/tmp/ai-tools-sync.out.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/ai-tools-sync.err.log</string>
  </dict>
</plist>
PLIST

/usr/bin/plutil -lint "$PLIST_PATH" >/dev/null

launchctl bootout "gui/$(id -u)" "$PLIST_PATH" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"

launchctl list | /usr/bin/grep "$LABEL" || true

printf "Installed %s\n" "$PLIST_PATH"
