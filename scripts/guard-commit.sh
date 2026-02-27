#!/usr/bin/env bash
set -euo pipefail

ALLOWED_EMAIL="loup.peluso@gmail.com"
email=$(git config user.email)

if [ "$email" != "$ALLOWED_EMAIL" ]; then
  echo "ERROR: commit author email is '$email', expected '$ALLOWED_EMAIL'"
  echo "Run: git config user.email $ALLOWED_EMAIL"
  exit 1
fi

day=$(date +%u)   # 1=Mon ... 7=Sun
hour=$(date +%H)

if [ "$day" -le 5 ] && [ "$hour" -ge 9 ] && [ "$hour" -lt 18 ]; then
  echo "ERROR: commits are not allowed Mon-Fri 9:00-18:00 (current: $(date))"
  echo "Use 'git commit --no-verify' to bypass if needed."
  exit 1
fi
