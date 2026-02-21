# sync-ai-configs

Sync AI configs (agents, skills, MCP servers, client config) to Codex, Cursor, and Gemini.

## Installation

From the **repository root** (parent of `scripts/client-sync/`):

```bash
pip install -e scripts/client-sync/
```

Or install dependencies only and run the script directly:

```bash
pip install -r scripts/client-sync/requirements.txt
python scripts/client-sync/sync_ai_configs.py
```

### Auto-sync setup

To install the LaunchAgent, venv, and client version lock:

```bash
./scripts/auto-sync/install_auto_sync.sh
```

This creates `scripts/.venv/`, enforces the repo-owned `scripts/.client-versions.json`, and blocks syncs if client major/minor versions change.

## Usage

Run from the **repository root** so the script finds `config/prompts/`, `config/skills/`, `config/mcp-servers/`, `config/client-settings/`:

```bash
# After pip install -e scripts/client-sync/
sync-ai-configs

# Or run script directly
python scripts/client-sync/sync_ai_configs.py
```

### Options

- `--capture-oauth` — Copy OAuth token caches from clients into `config/mcp-servers/secrets/`
- `--force` — Update `scripts/.client-versions.json` with local client versions, then sync

## Testing

```bash
pip install -e "scripts/client-sync/[dev]"
pytest scripts/client-sync/tests/
```

## Project layout

```
scripts/client-sync/
├── pyproject.toml      # Project config, dependencies, entry point
├── requirements.txt    # Pinned deps for non-package install
├── sync_ai_configs.py  # Main script
├── helpers.py
├── clients/            # Per-client sync logic (Codex, Cursor, Gemini)
├── tests/              # Unit tests (pytest)
└── README.md
```
