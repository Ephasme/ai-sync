#!/usr/bin/env bash
set -euo pipefail

ROOT="/Users/loup/code/perso/ai-tools"
SYNC_SCRIPT="${ROOT}/scripts/client-sync/sync_ai_configs.py"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

WATCHEXEC="/opt/homebrew/bin/watchexec"
NOTIFY_SCRIPT="${ROOT}/scripts/auto-sync/notify_sync.sh"
ERR_LOG="/tmp/ai-tools-sync.err.log"

rotate_log() {
  local path="$1"
  local max_bytes="$2"
  local max_files="$3"

  if [ ! -f "$path" ]; then
    return 0
  fi

  local size
  size="$(/usr/bin/stat -f%z "$path" 2>/dev/null || echo 0)"
  if [ "$size" -lt "$max_bytes" ]; then
    return 0
  fi

  local i
  i=$((max_files - 1))
  while [ "$i" -ge 1 ]; do
    if [ -f "${path}.${i}" ]; then
      if [ "$i" -eq $((max_files - 1)) ]; then
        /bin/rm -f "${path}.${i}"
      else
        /bin/mv -f "${path}.${i}" "${path}.$((i + 1))"
      fi
    fi
    i=$((i - 1))
  done

  /bin/mv -f "$path" "${path}.1"
}

if [ ! -x "$WATCHEXEC" ]; then
  echo "watchexec not found at ${WATCHEXEC}. Install with: brew install watchexec" >&2
  exit 1
fi

rotate_log "$ERR_LOG" $((5 * 1024 * 1024)) 1000

VENV_PYTHON="${ROOT}/scripts/.venv/bin/python3"
if [ ! -x "$VENV_PYTHON" ]; then
  echo "Virtualenv python not found at ${VENV_PYTHON}. Run: ${ROOT}/scripts/auto-sync/install_auto_sync.sh" >&2
  exit 1
fi

exec "$WATCHEXEC" \
  -w "${ROOT}/config/mcp-servers" \
  -w "${ROOT}/config/prompts" \
  -w "${ROOT}/config/skills" \
  -w "${ROOT}/config/client-settings" \
  -- "output=\$(${VENV_PYTHON} \"${SYNC_SCRIPT}\" 2>&1); exit_code=\$?; echo \"\$output\"; summary=\$(${VENV_PYTHON} \"${ROOT}/scripts/shared/sync_summary.py\" 2>/dev/null || true); [ -n \"\$summary\" ] || summary='agents=? skills=? servers=?'; if [ \"\$exit_code\" -eq 0 ]; then msg=\"Sync finished (\$summary)\"; else msg=\"Sync failed (\$summary)\"; fi; \"${NOTIFY_SCRIPT}\" \"\$msg\""
