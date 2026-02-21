#!/usr/bin/env bash
set -euo pipefail

OSASCRIPT="/usr/bin/osascript"
TITLE="AI Config Sync"
MESSAGE="${1:-Sync finished}"
# Escape for AppleScript: \ -> \\ and " -> \"
MESSAGE_ESC="${MESSAGE//\\/\\\\}"
MESSAGE_ESC="${MESSAGE_ESC//\"/\\\"}"

"${OSASCRIPT}" -e "display notification \"${MESSAGE_ESC}\" with title \"${TITLE}\""
