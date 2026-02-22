#!/usr/bin/env bash
set -euo pipefail

# Load OP_ACCOUNT from rc when run manually (LaunchAgent sources it). Don't source rc files—
# they may contain shell-specific syntax that fails when run under bash.
if [ -z "${OP_ACCOUNT:-}" ] && [ -z "${OP_SERVICE_ACCOUNT_TOKEN:-}" ]; then
  for rc in ~/.zshrc ~/.bashrc; do
    [ -f "$rc" ] || continue
    val="$(grep -E '^\s*export\s+OP_ACCOUNT=' "$rc" 2>/dev/null | head -1 | sed -E 's/.*OP_ACCOUNT=["'\'']([^"'\'']*)["'\''].*/\1/')"
    if [ -n "$val" ]; then
      export OP_ACCOUNT="$val"
      break
    fi
  done
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
NOTIFY_SCRIPT="${ROOT}/scripts/auto-sync/notify_sync.sh"
SUMMARY_SCRIPT="${ROOT}/scripts/shared/sync_summary.py"
SYNC_CMD="${ROOT}/scripts/.venv/bin/sync-ai-configs"
if [ ! -x "$SYNC_CMD" ]; then
  SYNC_CMD="$(command -v sync-ai-configs || true)"
fi
if [ -z "${SYNC_CMD:-}" ]; then
  echo "sync-ai-configs command not found. Run install_auto_sync.sh first." >&2
  exit 1
fi

if [ -z "${OP_ACCOUNT:-}" ] && [ -z "${OP_SERVICE_ACCOUNT_TOKEN:-}" ]; then
  echo "OP_ACCOUNT or OP_SERVICE_ACCOUNT_TOKEN required. Run install_auto_sync.sh --op-account NAME first." >&2
  exit 1
fi

set +e
if [ -n "${OP_ACCOUNT:-}" ]; then
  output="$("$SYNC_CMD" --plain --op-account "$OP_ACCOUNT" 2>&1)"
else
  output="$("$SYNC_CMD" --plain 2>&1)"
fi
exit_code=$?
set -e

echo "$output"
summary="$(python3 "${SUMMARY_SCRIPT}" 2>/dev/null || true)"
[ -n "$summary" ] || summary="agents=? skills=? servers=?"

if [ "$exit_code" -eq 0 ]; then
  msg="Sync finished (${summary})"
else
  # Always show the actual error: prefer explicit "Sync failed: "; else error-like lines; else last line; else trailing output
  err="$(echo "$output" | /usr/bin/grep "Sync failed: " 2>/dev/null | /usr/bin/tail -1 | /usr/bin/sed "s/.*Sync failed: //" | /usr/bin/head -c 200)" || true
  [ -n "$err" ] || err="$(echo "$output" | /usr/bin/grep -E "Version mismatch:|Error:|ERROR:|Failed|Missing " 2>/dev/null | /usr/bin/tail -1 | /usr/bin/head -c 200)" || true
  [ -n "$err" ] || err="$(echo "$output" | /usr/bin/sed '/^[[:space:]]*$/d' | /usr/bin/tail -1 | /usr/bin/head -c 200)"
  [ -n "$err" ] || err="$(echo "$output" | /usr/bin/tr '\n' ' ' | rev | /usr/bin/head -c 200 | rev | /usr/bin/sed 's/^[[:space:]]*//')"
  [ -n "$err" ] || err="(no output captured)"
  msg="Sync failed: ${err}"
fi

"${NOTIFY_SCRIPT}" "${msg}" 2>/dev/null || true
exit "$exit_code"
