#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/release_checks.sh <version>

Version must be X.Y.Z (no leading "v").
EOF
}

if [[ "${1:-}" == "" ]]; then
  usage
  exit 1
fi

VERSION="$1"

if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Version must look like X.Y.Z (got '$VERSION')." >&2
  exit 1
fi

if [[ ! -f pyproject.toml ]]; then
  echo "pyproject.toml not found in current directory." >&2
  exit 1
fi

if ! command -v poetry >/dev/null; then
  echo "poetry not found. Install Poetry to continue." >&2
  exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Working tree is not clean. Commit or stash changes first." >&2
  exit 1
fi

TAG="v${VERSION}"
if git rev-parse -q --verify "refs/tags/${TAG}" >/dev/null; then
  echo "Tag ${TAG} already exists." >&2
  exit 1
fi
