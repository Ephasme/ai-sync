# AI Research Doc

A single canonical repository for AI agent configuration across **Codex**, **Cursor**, and **Gemini CLI**. Define agents, skills, MCP servers, and client settings once; sync them to every client with one command.

## Overview

This repo provides:

- **Agents** – Sub-agents derived from prompts with per-client metadata
- **Skills** – Agent Skills (SKILL.md) mirrored to all clients
- **MCP servers** – Model Context Protocol servers with centralized config and secrets
- **Client configuration** – Generic settings (subagents, mode) derived into client-specific configs
- **OAuth token portability** – Capture and restore MCP OAuth caches across machines

All syncing is **idempotent**: identical targets cause no writes; changed targets are backed up (`tar.gz`) before overwrite.

---

## Quick start

```bash
pip install -r scripts/requirements.txt
sync-ai-configs
# Or: pip install -r scripts/client-sync/requirements.txt && python scripts/client-sync/sync_ai_configs.py
```

### Auto-sync (LaunchAgent + notifications)

Use the installer to set up a LaunchAgent that watches changes and syncs automatically with notifications:

```bash
/Users/loup/code/perso/ai-tools/scripts/auto-sync/install_auto_sync.sh
```

Notes:
- Creates a venv at `scripts/.venv/` and runs syncs inside it.
- Enforces the repo-owned `scripts/.client-versions.json` (major/minor must match installed clients).
- Auto-sync is blocked and a notification is shown if client major/minor versions differ.

### Prerequisites

- Python 3.10+
- [Codex](https://developers.openai.com/codex), [Cursor](https://cursor.com), and/or [Gemini CLI](https://geminicli.com) installed
- For MCP stdio servers: Node.js (`npx`)

---

## Repository structure

```
.
├── config/
│   ├── prompts/               # Agent prompts (source of truth)
│   ├── senior_software_engineer.md
│   ├── senior_software_engineer.metadata.yaml
│   └── ...
│   ├── skills/                # Agent Skills
│   │   ├── create-skill/
│   │   │   └── SKILL.md
│   │   └── ...
│   ├── mcp-servers/
│   │   ├── servers.yaml        # Canonical MCP server manifest
│   │   └── secrets/
│   │       ├── secrets.example.yaml
│   │       ├── secrets.yaml    # Gitignored – API keys, OAuth credentials
│   │       ├── codex-auth.json # Gitignored – OAuth cache (captured)
│   │       └── gemini-mcp-oauth-tokens.json
│   └── client-settings/
│       ├── settings.example.yaml  # Template (tracked)
│       └── settings.yaml          # Local overrides (gitignored; copy from example)
├── scripts/
│   ├── auto-sync/             # LaunchAgent + notifications
│   │   ├── install_auto_sync.sh
│   │   ├── watch_ai_sync.sh
│   │   └── notify_sync.sh
│   ├── client-sync/           # Python: sync-ai-configs
│   │   ├── pyproject.toml
│   │   ├── sync_ai_configs.py
│   │   ├── clients/
│   │   ├── tests/
│   │   └── ...
│   └── shared/                # Shared helpers (version checks, summaries)
│       ├── check_client_versions.py
│       └── sync_summary.py
├── scripts/requirements.txt
├── scripts/.client-versions.json
├── scripts/.venv/
└── .sync_backups/              # Tar.gz backups before overwrite
```

---

## Sync script

### Usage

```bash
sync-ai-configs
```

Run from the **repository root** so the script finds `config/prompts/`, `config/skills/`, `config/mcp-servers/`, `config/client-settings/`.

### Options

| Option | Description |
|--------|--------------|
| (none) | Full sync: agents → skills → MCP servers → client config |
| `--capture-oauth` | Copy OAuth token caches from clients into `config/mcp-servers/secrets/` for portability |

### Sync order

1. **Agents** – From `config/prompts/*.md` → `~/.codex/agents/`, `~/.cursor/agents/`, `~/.gemini/agents/`
2. **Skills** – From `config/skills/*/` → `~/.codex/skills/`, `~/.cursor/skills/`, `~/.gemini/skills/`
3. **MCP servers** – From `config/mcp-servers/servers.yaml` → client MCP configs, OAuth cache restore
4. **Client config** – From `config/client-settings/settings.yaml` → approval policy, sandbox, features

### Sync strategy

- **Agents, skills, client config**: No backup. Files overwritten if they exist. Untracked agents/skills (not in config/prompts/ or config/skills/) are left alone.
- **Client config**: Deep-merge with existing; ai-tools keys overwrite on conflict.
- **MCP OAuth cache** (restore): Backup before overwrite.

---

## Agents

### Source structure

Each agent lives in `config/prompts/`:

```
config/prompts/
├── <agent_name>.md           # Prompt content (required)
└── <agent_name>.metadata.yaml   # Optional metadata
```

### Metadata schema (`config/prompts/<name>.metadata.yaml`)

Metadata is **generic** (client-agnostic). The sync script adapts it per client.

| Key | Description | Default |
|-----|-------------|---------|
| `slug` | Agent ID (kebab-case) | Derived from filename |
| `name` | Display name | From filename |
| `description` | Short description | Extracted from prompt |

Untracked agents (in client but not in `config/prompts/`) are left alone.

### Target layout per client

| Client | Target |
|--------|--------|
| Codex | `~/.codex/agents/<slug>/prompt.md` + `config.toml` |
| Cursor | `~/.cursor/agents/<slug>.md` (frontmatter) |
| Gemini | `~/.gemini/agents/<slug>.md` (frontmatter) |

---

## Skills

Skills are directories under `config/skills/` with a `SKILL.md` file. The sync script mirrors each skill to all three clients.

### Structure

```
config/skills/
└── <skill-name>/
    ├── SKILL.md          # Required
    ├── reference.md      # Optional
    ├── examples.md       # Optional
    └── scripts/          # Optional; copied if present
```

Paths containing `.venv`, `node_modules`, `__pycache__`, `.git`, or `.DS_Store` are skipped. Untracked skills (in client but not in `config/skills/`) are left alone.

### Targets

- `~/.codex/skills/<skill-name>/`
- `~/.cursor/skills/<skill-name>/`
- `~/.gemini/skills/<skill-name>/`

---

## MCP servers

### Manifest (`config/mcp-servers/servers.yaml`)

```yaml
servers:
  <server_id>:
    method: stdio | http | sse
    command: npx
    args: ["-y", "@modelcontextprotocol/server-xxx"]
    env:                         # Env var names (values from secrets.yaml)
      API_KEY: ""
    enabled: true
    clients: [codex, cursor, gemini]   # Optional; default: all
```

For HTTP/SSE:

```yaml
  remote-server:
    method: http
    url: "https://example.com/mcp"
    bearer_token_env_var: BEARER_TOKEN
```

### Secrets (`config/mcp-servers/secrets/secrets.yaml`)

Create from `secrets.example.yaml` and fill values. **Never commit** – folder is gitignored.

```yaml
servers:
  <server_id>:
    env:                    # Injected into client configs
      API_KEY: "actual-value"
      BEARER_TOKEN: "..."
    auth:                   # Cursor OAuth static credentials
      CLIENT_ID: "..."
      CLIENT_SECRET: "..."
```

### Client targets

| Client | Target | Strategy |
|--------|--------|----------|
| Codex | `~/.codex/config.toml` `[mcp_servers.<id>]` | Merge |
| Codex | `~/.codex/mcp.env` | Bearer token exports (source before running Codex) |
| Cursor | `~/.cursor/mcp.json` | Overwrite `mcpServers` |
| Gemini | `~/.gemini/settings.json` `mcpServers` | Deep-merge |

### OAuth token portability

Some MCP servers use OAuth. To avoid re-authenticating on each new machine:

1. **Capture** (on machine A, after logging in):  
   `sync-ai-configs --capture-oauth`
2. Sync `config/mcp-servers/secrets/` via a secure channel (rsync, 1Password, etc.)
3. **Restore** (on machine B): Run `sync-ai-configs` – OAuth caches are restored automatically

| Client | Token cache (client) | Stash (repo) |
|--------|----------------------|--------------|
| Codex | `~/.codex/auth.json` | `config/mcp-servers/secrets/codex-auth.json` |
| Gemini | `~/.gemini/mcp-oauth-tokens.json` | `config/mcp-servers/secrets/gemini-mcp-oauth-tokens.json` |
| Cursor | TBD | TBD |

---

## Client configuration

Single YAML definition → derived into Codex, Gemini, and Cursor.

### Schema (`config/client-settings/settings.yaml`)

| Key | Values | Description |
|-----|--------|-------------|
| `subagents` | `true` \| `false` | Enable multi-agents, sub-agents, child-prompts, AGENTS.md, etc. |
| `mode` | `ask` \| `ask-once` \| `full-access` | Approval / restriction mode |

### Mode semantics

| Mode | Meaning |
|------|---------|
| `ask` | Prompt for approval every time before acting |
| `ask-once` | Auto-approve safe ops, prompt for risky ones (where supported) |
| `full-access` | No approval prompts, no restrictions (YOLO) |

### Client mapping (from official docs)

| Generic | Codex | Gemini | Cursor |
|----------|-------|--------|--------|
| **subagents: true** | `features.multi_agent`, `features.child_agents_md` | `experimental.enableAgents` | — |
| **mode: ask** | `approval_policy=on-request`, `sandbox_mode=workspace-write` | `general.defaultApprovalMode=default` | `permissions: {allow:[], deny:[]}` |
| **mode: ask-once** | `approval_policy=untrusted`, `sandbox_mode=workspace-write` | `general.defaultApprovalMode=auto_edit` | same as `ask` |
| **mode: full-access** | `approval_policy=never`, `sandbox_mode=danger-full-access` | `general.defaultApprovalMode=yolo` | `allow: [Shell(*), Read(*), Write(*), WebFetch(*), Mcp(*:*)]` |

### Client targets

| Client | Target | Strategy |
|--------|--------|----------|
| Codex | `~/.codex/config.toml` | Deep-merge with existing; ai-tools keys overwrite. No backup. |
| Gemini | `~/.gemini/settings.json` | Deep-merge with existing; ai-tools keys overwrite. No backup. |
| Cursor | `~/.cursor/cli-config.json` | Deep-merge with existing; ai-tools keys overwrite. No backup. |

---

## Dependencies

The sync tool lives in `scripts/client-sync/` as a Python project:

```bash
pip install -e scripts/client-sync/
```

Dependencies: `pyyaml>=6.0`, `tomli>=2.0`, `tomli-w>=1.0`

---

## .gitignore

- `config/mcp-servers/secrets/*` (except `secrets.example.yaml`)
- `config/client-settings/settings.yaml`
- `knowledge-base/*`
- `.sync_backups/`
- `.env`, Python bytecode, virtual envs, `.pytest_cache/`, `node_modules/`, `.DS_Store`, etc.

---

## Workflow summary

### New machine setup

1. Clone repo
2. `pip install -r scripts/requirements.txt`
3. Create `config/mcp-servers/secrets/secrets.yaml` from `secrets.example.yaml` and fill API keys
4. Copy `config/client-settings/settings.example.yaml` to `config/client-settings/settings.yaml` and edit if needed
5. (Optional) Copy OAuth caches into `config/mcp-servers/secrets/` if synced from another machine
6. `sync-ai-configs`
7. For Codex HTTP MCP servers: `source ~/.codex/mcp.env` in shell profile

### Adding an MCP server

1. Edit `config/mcp-servers/servers.yaml`
2. Add secrets to `config/mcp-servers/secrets/secrets.yaml`
3. Run `sync-ai-configs`

### Adding an agent

1. Add `config/prompts/<name>.md`
2. (Optional) Add `config/prompts/<name>.metadata.yaml`
3. Run `sync-ai-configs`

### Adding a skill

1. Create `config/skills/<skill-name>/SKILL.md`
2. Run `sync-ai-configs`

### Changing client mode

1. Edit `config/client-settings/settings.yaml` (`subagents`, `mode`)
2. Run `sync-ai-configs`

---

## References

- [Codex config reference](https://developers.openai.com/codex/config-reference/)
- [Codex security & sandbox](https://developers.openai.com/codex/security)
- [Gemini CLI configuration](https://geminicli.com/docs/reference/configuration)
- [Cursor CLI permissions](https://docs.cursor.com/cli/reference/permissions)
- [Agent Skills standard](https://github.com/anthropics/anthropic-cookbook/blob/main/agent-skills/README.md)
