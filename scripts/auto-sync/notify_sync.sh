#!/usr/bin/env bash
set -euo pipefail

OSASCRIPT="/usr/bin/osascript"
TITLE="AI Config Sync"
MESSAGE="${1:-Sync finished}"

"${OSASCRIPT}" -e "display notification \"${MESSAGE}\" with title \"${TITLE}\""
