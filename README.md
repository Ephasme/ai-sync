# ai-sync

A self-contained local config store for **Codex**, **Cursor**, and **Gemini CLI**. Define agents, skills, MCP servers, and client settings once in `~/.ai-sync/`, then sync them to every client with one command.

License: PolyForm Noncommercial 1.0.0 (non-commercial use only).

## Overview

This repo provides:

- **The ai-sync CLI** – Manage `~/.ai-sync/` and run syncs
- **Agents** – Sub-agents derived from prompts with per-client metadata
- **Skills** – Agent Skills (SKILL.md) mirrored to all clients
- **MCP servers** – Model Context Protocol servers with centralized config and secrets
- **Client configuration** – Generic settings (subagents, mode) derived into client-specific configs
- **OAuth token portability** – Manual copy of client OAuth caches across machines (automated capture/restore planned)

All syncing is **idempotent**: identical targets cause no writes; changed targets overwrite in place.

---

## Install

### End users (recommended)

```bash
pipx install ai-sync
```

### Local development

```bash
poetry sync --with dev
```

Optional (task runner):

```bash
brew install just
just install
just test
just release 0.1.4
```

## Quick start

```bash
ai-sync setup --op-account NAME
ai-sync import --repo /path/to/config-repo   # optional
ai-sync sync
```

### Prerequisites

- Python 3.11+
- [Codex](https://developers.openai.com/codex), [Cursor](https://cursor.com), and/or [Gemini CLI](https://geminicli.com) installed
- 1Password Desktop app (for `OP_ACCOUNT`) or `OP_SERVICE_ACCOUNT_TOKEN` for service accounts
- For MCP stdio servers: Node.js (`npx`), [uv](https://docs.astral.sh/uv/) (`uvx` for workspace-mcp), `pip install mcp-server-fetch` for fetch

---

## Project structure

This repo ships the sync tool. Runtime data lives in `~/.ai-sync/`.

```
Repo:
.
├── src/
│   └── ai_sync/               # Python: ai-sync
│       └── .client-versions.json  # Supported client versions (packaged)
├── tests/
├── pyproject.toml
└── README.md

Runtime:
~/.ai-sync/
├── config.toml                # op_account, secret_provider
├── .env.tpl                   # MCP secrets (op:// refs resolved via 1Password)
├── config/
│   ├── prompts/
│   ├── skills/
│   ├── rules/
│   ├── mcp-servers.yaml
│   └── client-settings.yaml
└── cache/
```

Import repo layout:
```
<repo>/
├── prompts/
├── skills/
├── mcp-servers.yaml
├── client-settings.yaml
├── .env.tpl            # optional
└── rules/              # optional
```

---

## ai-sync

### Usage

```bash
ai-sync setup --op-account NAME
ai-sync import --repo /path/to/config-repo   # optional
ai-sync sync
```

Running `ai-sync` with no subcommand defaults to `sync`.
Other commands: `ai-sync setup`, `ai-sync import`, `ai-sync doctor`.

### Sync options

| Option | Description |
|--------|--------------|
| (none) | Full sync: agents → skills → MCP servers → client config |
| `--force` | Update the packaged client version lock (dev-only), then sync |
| `--no-interactive` | Skip interactive prompts |
| `--plain` | Plain output (implies `--no-interactive`) |
| `--override` / `--override-json` | Override manifest leaf values (e.g. `/servers/context7/enabled=false`) |

### Sync order

1. **Agents** – From `~/.ai-sync/config/prompts/*.md` → `~/.codex/agents/`, `~/.cursor/agents/`, `~/.gemini/agents/`
2. **Skills** – From `~/.ai-sync/config/skills/*/` → `~/.codex/skills/`, `~/.cursor/skills/`, `~/.gemini/skills/`
3. **MCP servers** – From `~/.ai-sync/config/mcp-servers.yaml` → client MCP configs, MCP instructions
4. **Client config** – From `~/.ai-sync/config/client-settings.yaml` → approval policy, sandbox, features

### Sync strategy

- **Agents, skills, client config**: Files overwritten if they exist. Untracked agents/skills (not in `~/.ai-sync/config/prompts/` or `~/.ai-sync/config/skills/`) are left alone.
- **Client config**: Deep-merge with existing; ai-tools keys overwrite on conflict.
- **MCP servers**: Merged with existing; managed servers updated, user-added servers preserved.

---

## Agents

### Source structure

Each agent lives in `~/.ai-sync/config/prompts/`:

```
~/.ai-sync/config/prompts/
├── <agent_name>.md           # Prompt content (required)
└── <agent_name>.metadata.yaml   # Optional metadata
```

### Metadata schema (`~/.ai-sync/config/prompts/<name>.metadata.yaml`)

Metadata is **generic** (client-agnostic). The sync script adapts it per client.

| Key | Description | Default |
|-----|-------------|---------|
| `slug` | Agent ID (kebab-case) | Derived from filename |
| `name` | Display name | From filename |
| `description` | Short description | Extracted from prompt |

Untracked agents (in client but not in `~/.ai-sync/config/prompts/`) are left alone.

### Target layout per client

| Client | Target |
|--------|--------|
| Codex | `~/.codex/agents/<slug>/prompt.md` + `config.toml` |
| Cursor | `~/.cursor/agents/<slug>.md` (frontmatter) |
| Gemini | `~/.gemini/agents/<slug>.md` (frontmatter) |

---

## Skills

Skills are directories under `~/.ai-sync/config/skills/` with a `SKILL.md` file. The sync script mirrors each skill to all three clients.

### Structure

```
~/.ai-sync/config/skills/
└── <skill-name>/
    ├── SKILL.md          # Required
    ├── reference.md      # Optional
    ├── examples.md       # Optional
    └── scripts/          # Optional; copied if present
```

Paths containing `.venv`, `node_modules`, `__pycache__`, `.git`, or `.DS_Store` are skipped. Untracked skills (in client but not in `~/.ai-sync/config/skills/`) are left alone.

### Targets

- `~/.codex/skills/<skill-name>/`
- `~/.cursor/skills/<skill-name>/`
- `~/.gemini/skills/<skill-name>/`

---

## MCP servers

### Manifest (`~/.ai-sync/config/mcp-servers.yaml`)

```yaml
servers:
  <server_id>:
    method: stdio | http | sse
    command: npx
    args: ["-y", "@modelcontextprotocol/server-xxx"]
    enabled: true
    clients: [codex, cursor, gemini]   # Optional; default: all
    timeout_seconds: 60               # Optional; startup/tool timeout (seconds)
    trust: true                        # Optional; Cursor/Gemini: auto-approve tools
```

**STDIO servers** – `command`, `args`; env vars use `"${VAR}"` refs resolved from `~/.ai-sync/.env.tpl`.

**HTTP/SSE servers** – `url`, `httpUrl`; optional `bearer_token_env_var` for Codex.

**HTTP with OAuth** – `httpUrl` + `oauth.enabled: true`; `clientId`/`clientSecret` from `~/.ai-sync/.env.tpl` via `"${VAR}"`:

```yaml
  google-maps-grounding-lite:
    method: http
    httpUrl: https://mapstools.googleapis.com/mcp
    oauth:
      enabled: true
      clientId: "${GOOGLE_MAPS_GROUNDING_LITE_CLIENT_ID}"
      clientSecret: "${GOOGLE_MAPS_GROUNDING_LITE_CLIENT_SECRET}"
```

### Configured servers

| Server | Method | Description |
|--------|--------|-------------|
| context7 | stdio | Documentation lookup (`@upstash/context7-mcp`) |
| fetch | stdio | URL fetch → markdown (`python -m mcp_server_fetch`) |
| playwright | stdio | Browser control (`@playwright/mcp`) |
| exa | http | Search API |
| google-workspace-perso | stdio | Gmail, Calendar, Drive (personal @gmail.com, separate OAuth) |
| google-workspace-pro | stdio | Gmail, Calendar, Drive (work @sherpas.com, separate OAuth) |
| google-maps-grounding-lite | http | Maps grounding (OAuth) |

### Secrets (`~/.ai-sync/.env.tpl`)

All MCP secrets live in `~/.ai-sync/.env.tpl`. Use `op://` references for 1Password:

```
CONTEXT7_API_KEY=op://Private/AI Tools Secrets/CONTEXT7_API_KEY
EXA_API_KEY=op://Private/AI Tools Secrets/EXA_API_KEY
GOOGLE_OAUTH_CLIENT_ID_PERSO=op://Private/AI Tools Secrets/GOOGLE_OAUTH_CLIENT_ID_PERSO
...
```

In `mcp-servers.yaml`, reference them with `"${VAR_NAME}"` in each server's `env` or `oauth` block. The sync script resolves these at runtime via 1Password (requires `OP_ACCOUNT` or `OP_SERVICE_ACCOUNT_TOKEN`).

**Requirements**: 1Password Desktop app (for `OP_ACCOUNT`) or `OP_SERVICE_ACCOUNT_TOKEN` (service account).

### Client targets

| Client | Target | Strategy |
|--------|--------|----------|
| Codex | `~/.codex/config.toml` `[mcp_servers.<id>]` | Merge |
| Codex | `~/.codex/mcp.env` | Bearer token exports (source before running Codex) |
| Cursor | `~/.cursor/mcp.json` | Overwrite `mcpServers` |
| Gemini | `~/.gemini/settings.json` `mcpServers` | Deep-merge |

### OAuth token portability

OAuth tokens are stored per client (e.g. `~/.gemini/mcp-oauth-tokens.json`). To move them between machines, copy the client token files manually via a secure channel (rsync, 1Password, etc.). Automated capture/restore is planned.

---

## Client configuration

Single YAML definition → derived into Codex, Gemini, and Cursor.

### Schema (`~/.ai-sync/config/client-settings.yaml`)

| Key | Values | Description |
|-----|--------|-------------|
| `experimental` | `true` \| `false` | Enable experimental/preview features; suppress experimental warnings where supported |
| `subagents` | `true` \| `false` | Enable multi-agents, sub-agents, child-prompts, AGENTS.md |
| `mode` | `strict` \| `normal` \| `yolo` | Approval / restriction mode (default: `normal`) |
| `tools.sandbox` | `true` \| `false` | Gemini only. When false, allow MCP tools filesystem access (uvx, etc.) |

### Mode semantics

| Mode | Meaning |
|------|---------|
| `strict` | Most restrictive: read-only where supported; approval required for actions |
| `normal` | More permissive; allow reads/writes while still requiring approval for destructive actions where supported |
| `yolo` | No approval prompts, no restrictions (full access) |

### Client mapping (from official docs)

| Generic | Codex | Gemini | Cursor |
|----------|-------|--------|--------|
| **subagents: true** | `features.multi_agent`, `features.child_agents_md` | `experimental.enableAgents` | — |
| **experimental: true** | `suppress_unstable_features_warning` | `experimental.plan` | — |
| **tools.sandbox: false** | — | `tools.sandbox` | — |
| **mode: strict** | `approval_policy=on-request`, `sandbox_mode=read-only` | `general.defaultApprovalMode=plan`, `tools.sandbox=true` | `permissions: {allow:[], deny:[]}` |
| **mode: normal** | `approval_policy=untrusted`, `sandbox_mode=danger-full-access` | `general.defaultApprovalMode=auto_edit`, `tools.sandbox=false` | `allow: [Shell(*), Read(*), Write(*), WebFetch(*), Mcp(*:*)]` |
| **mode: yolo** | `approval_policy=never`, `sandbox_mode=danger-full-access` | `general.defaultApprovalMode=yolo`, `tools.sandbox=false` | `allow: [Shell(*), Read(*), Write(*), WebFetch(*), Mcp(*:*)]` |

### Client targets

| Client | Target | Strategy |
|--------|--------|----------|
| Codex | `~/.codex/config.toml` | Deep-merge with existing; ai-tools keys overwrite. No backup. |
| Gemini | `~/.gemini/settings.json` | Deep-merge with existing; ai-tools keys overwrite. No backup. |
| Cursor | `~/.cursor/cli-config.json` | Deep-merge with existing; ai-tools keys overwrite. No backup. |

---

## Dependencies

This project uses Poetry for dependency management and packaging:

```bash
poetry sync --with dev
```

Dependencies: `pyyaml>=6.0`, `tomli>=2.0`, `tomli-w>=1.0`, and others (see `pyproject.toml`).

### Testing

```bash
poetry run pytest
```

---

## Packaging & Release

This project is published to PyPI as `ai-sync`.

### Release checklist

1. Update README if anything changed in CLI behavior or setup.
2. Run the release:

```bash
just release X.Y.Z
```

This runs `./scripts/release_checks.sh`, `poetry lock`, bumps the version, runs tests, commits, tags, and pushes.

3. GitHub Actions runs tests, builds artifacts, publishes to PyPI, and creates a GitHub Release.

### Notes

- Use `pipx install ai-sync` for end users.
- Keep `ai-sync` as the only supported CLI name.

---

## .gitignore

If you maintain a separate config repo for `ai-sync import`, consider ignoring:

- `config/mcp-servers.yaml`
- `config/client-settings.yaml`
- `.env.tpl`
- `knowledge-base/*`
- `.env`, Python bytecode, virtual envs, `.pytest_cache/`, `node_modules/`, `.DS_Store`, etc.

---

## Workflow summary

### New machine setup

1. Clone repo (tooling only)
2. `poetry sync --with dev`
3. `ai-sync setup --op-account NAME` (or set `OP_SERVICE_ACCOUNT_TOKEN`)
4. `ai-sync import --repo /path/to/config-repo` (optional)
5. Ensure `~/.ai-sync/.env.tpl` has correct 1Password refs
6. `ai-sync sync`
7. For Codex HTTP MCP servers: `source ~/.codex/mcp.env` in shell profile

### Adding an MCP server

1. Edit `~/.ai-sync/config/mcp-servers.yaml`
2. Add required vars to `~/.ai-sync/.env.tpl` (use `op://` refs for secrets)
3. Run `ai-sync sync`

### Adding an agent

1. Add `~/.ai-sync/config/prompts/<name>.md`
2. (Optional) Add `~/.ai-sync/config/prompts/<name>.metadata.yaml`
3. Run `ai-sync sync`

### Adding a skill

1. Create `~/.ai-sync/config/skills/<skill-name>/SKILL.md`
2. Run `ai-sync sync`

### Changing client mode

1. Edit `~/.ai-sync/config/client-settings.yaml` (`subagents`, `mode`)
2. Run `ai-sync sync`

---

## References

- [Codex config reference](https://developers.openai.com/codex/config-reference/)
- [Codex security & sandbox](https://developers.openai.com/codex/security)
- [Gemini CLI configuration](https://geminicli.com/docs/reference/configuration)
- [Cursor CLI permissions](https://docs.cursor.com/cli/reference/permissions)
- [Agent Skills standard](https://github.com/anthropics/anthropic-cookbook/blob/main/agent-skills/README.md)
