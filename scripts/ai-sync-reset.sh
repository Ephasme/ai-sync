#!/usr/bin/env bash
set -euo pipefail

# Usage: ai-sync-reset.sh [PROJECT_ROOT]
# Removes all ai-sync managed outputs from a project directory.

PROJECT_ROOT="${1:-.}"
PROJECT_ROOT="$(cd "$PROJECT_ROOT" && pwd)"

echo "Resetting ai-sync outputs in: $PROJECT_ROOT"

# 1. Remove client output directories
for dir in .cursor .codex .gemini .claude; do
  if [ -d "$PROJECT_ROOT/$dir" ]; then
    echo "  rm -rf $dir/"
    rm -rf "$PROJECT_ROOT/$dir"
  fi
done

# 2. Remove standalone managed files
for file in .mcp.json CLAUDE.md .env.ai-sync; do
  if [ -f "$PROJECT_ROOT/$file" ]; then
    echo "  rm $file"
    rm -f "$PROJECT_ROOT/$file"
  fi
done

# 3. Remove ai-sync internal state (sources, state, rules, plan) but keep
#    .ai-sync.yaml, .ai-sync.local.yaml, and instructions.md
for sub in sources state rules last-plan.yaml; do
  target="$PROJECT_ROOT/.ai-sync/$sub"
  if [ -e "$target" ]; then
    echo "  rm -rf .ai-sync/$sub"
    rm -rf "$target"
  fi
done

# 4. Strip managed marker blocks from AGENTS.md
AGENTS="$PROJECT_ROOT/AGENTS.md"
if [ -f "$AGENTS" ]; then
  if grep -q '<!-- BEGIN ai-sync:' "$AGENTS"; then
    echo "  Stripping ai-sync managed blocks from AGENTS.md"
    perl -0777 -i -pe 's/\n*<!-- BEGIN ai-sync:[\w:-]+ -->.*?<!-- END ai-sync:[\w:-]+ -->\n?//gs' "$AGENTS"
  fi
fi

# 5. Strip managed marker blocks from .gitignore
GITIGNORE="$PROJECT_ROOT/.gitignore"
if [ -f "$GITIGNORE" ]; then
  if grep -q '# BEGIN ai-sync:' "$GITIGNORE"; then
    echo "  Stripping ai-sync managed blocks from .gitignore"
    perl -0777 -i -pe 's/\n*# BEGIN ai-sync:[\w:-]+\n.*?# END ai-sync:[\w:-]+\n?//gs' "$GITIGNORE"
  fi
fi

# 6. Remove ai-sync pre-commit hook (restore chained original if present)
GIT_DIR="$(cd "$PROJECT_ROOT" && git rev-parse --git-dir 2>/dev/null || true)"
if [ -n "$GIT_DIR" ]; then
  HOOK="$GIT_DIR/hooks/pre-commit"
  CHAIN="$GIT_DIR/hooks/pre-commit.ai-sync-chain"
  if [ -f "$HOOK" ] && grep -q 'ai-sync:pre-commit-guard' "$HOOK"; then
    if [ -f "$CHAIN" ]; then
      echo "  Restoring original pre-commit hook"
      mv "$CHAIN" "$HOOK"
    else
      echo "  Removing ai-sync pre-commit hook"
      rm -f "$HOOK"
    fi
  fi
fi

echo ""
echo "Done. Manifest files (.ai-sync.yaml, .ai-sync.local.yaml) were preserved."
echo "Run 'ai-sync plan && ai-sync apply' to re-sync from scratch."
