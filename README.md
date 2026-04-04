# `ai-sync`

`ai-sync` synchronizes shared AI tooling artifacts into a project-local setup for Codex, Cursor, Gemini, and Claude Code.

The current workflow is:

1. Install `ai-sync` once on the machine.
2. Write a project `.ai-sync.yaml` or `.ai-sync.local.yaml`.
3. Run `ai-sync plan`.
4. Run `ai-sync apply [planfile]`.

License: PolyForm Noncommercial 1.0.0.

## Install

### End users

```bash
pipx install ai-sync
```

### Local development

```bash
poetry sync --with dev
```

Poetry is configured to create an in-project `.venv/`, which is what the `just` tasks use.

### Web UI development

For full hot reload during UI work, run the backend and frontend in separate terminals:

```bash
just ui-dev-api
just ui-dev-web
```

This starts:

- the FastAPI API with Python auto-reload on `http://127.0.0.1:8321`
- the Vite frontend with HMR on `http://127.0.0.1:5173`

If you want to keep using the packaged static UI instead of Vite HMR, use:

```bash
just build-ui-watch
```

Optional task runner:

```bash
brew install just
just install
just test
```

## Machine bootstrap

`install` is the only machine-level setup step. It writes `~/.ai-sync/config.toml` for auth/bootstrap settings such as the 1Password account identifier used by the CLI.

```bash
ai-sync install --op-account-identifier example.1password.com
```

The `--op-account-identifier` value must be a 1Password sign-in address such as `example.1password.com` or a 1Password user ID from `op account list`.

You can also authenticate with `OP_SERVICE_ACCOUNT_TOKEN`.

## Project workflow

### 1. Write `.ai-sync.yaml` or `.ai-sync.local.yaml`

Projects declare their config sources explicitly and select resources by fully scoped ids.

Example:

```yaml
sources:
  company:
    source: github.com/acme/company-ai-sync
    version: v1.4.0
  frontend:
    source: ../frontend-ai-sync

agents:
  - company/senior-software-engineer

skills:
  - company/code-review
  - frontend/react-review

commands:
  - company/session-summary

rules:
  - company/commit-conventions

mcp_servers:
  - company/context7

settings:
  mode: normal
  subagents: true
```

Notes:

- `.ai-sync.yaml` is the shared project manifest.
- `.ai-sync.local.yaml` is an optional local override. If it exists, `ai-sync` ignores `.ai-sync.yaml` entirely and uses the local file as the only project manifest.
- Remote sources must be pinned with `version`.
- Local path sources are allowed, but they are less portable than pinned remote sources.
- If your local SSH setup needs a different Git host than the shared manifest uses, prefer a local Git URL rewrite over checking machine-specific hosts into `.ai-sync.yaml`. For example:

```bash
git config url."git@example-git-host:example-org/".insteadOf "git@github.com:example-org/"
```

- Every selected resource must be scoped as `<sourceAlias>/<resourceId>`.

### 2. Run `plan`

`plan` resolves sources under the project, validates the selection, computes planned actions, and saves a plan artifact.

```bash
ai-sync plan
```

By default, the saved plan goes to `.ai-sync/last-plan.yaml`.

You can also choose an explicit output path:

```bash
ai-sync plan --out my-plan.yaml
```

### 3. Run `apply`

Use a reviewed plan:

```bash
ai-sync apply .ai-sync/last-plan.yaml
```

Or let `ai-sync` compute a fresh plan and execute it immediately:

```bash
ai-sync apply
```

The reviewed path is:

1. `ai-sync plan`
2. review the output / saved plan
3. `ai-sync apply <planfile>`

## Source repo layout

A source repo is a catalog of reusable artifacts:

```text
<source>/
├── agents/
│   └── <artifact-id>/
│       ├── artifact.yaml
│       ├── prompt.md
│       └── files/...   # optional reserved bundle assets
├── skills/
│   └── <artifact-id>/
│       ├── artifact.yaml
│       ├── prompt.md
│       └── files/...
├── commands/
│   └── <relative-path>/
│       ├── artifact.yaml
│       ├── prompt.md
│       └── files/...   # optional reserved bundle assets
├── rules/
│   └── <artifact-id>/
│       ├── artifact.yaml
│       ├── prompt.md
│       └── files/...   # optional reserved bundle assets
└── mcp_servers/
    └── <server-id>/
        └── artifact.yaml
```

### Resource ids

- Agents come from `agents/<name>/artifact.yaml` plus `agents/<name>/prompt.md` and are referenced as `<alias>/<name>`.
- Skills come from `skills/<name>/artifact.yaml` plus `skills/<name>/prompt.md` and are referenced as `<alias>/<name>`.
- Commands come from `commands/**/<name>/artifact.yaml` plus sibling `prompt.md` and are referenced as `<alias>/<relative-path>`.
- Rules come from `rules/<name>/artifact.yaml` plus `rules/<name>/prompt.md` and are referenced as `<alias>/<name>`.
- MCP servers come from `mcp_servers/<server-id>/artifact.yaml` and are referenced as `<alias>/<server-id>`.
- MCP-only: rendered subprocess `env` is synthesized from the server's declared `dependencies.env` entries after runtime resolution (optional per-entry `inject_as` renames the subprocess variable while keeping a unique dependency key for merging).

### Bundle artifact format

Every artifact bundle uses the same entry-file convention:

```text
<bundle>/
├── artifact.yaml
├── prompt.md   # prompt-bearing bundles only
└── files/...   # optional bundled assets
```

For prompts, skills, commands, and rules, `artifact.yaml` stores metadata only. The markdown body lives in sibling `prompt.md`:

```text
<bundle>/
├── artifact.yaml
└── prompt.md
```

Example command bundle:

```yaml
description: Session summary command
```

```md
Summarize the current session.
```

Notes:

- For prompts and rules, default ids are derived from the bundle directory name, not from the literal filename `artifact.yaml`.
- Skills are authored from `artifact.yaml` plus `prompt.md`; `ai-sync` generates the client-facing `SKILL.md` during sync.
- Skill assets live under `skills/<name>/files/...` in the source repo and are written to the client skill root without the `files/` prefix (for example `files/scripts/tool.py` becomes `scripts/tool.py`).
- Non-skill prompt-bearing bundles may also reserve `files/` in the source repo, but `ai-sync` does not sync those assets to client outputs yet.
- To migrate older inline `prompt:` bundles, use `migration/scripts/migrate_to_split_prompt_bundles.py`.

## Artifact dependencies

Each selected artifact can declare dependencies in `artifact.yaml` under the `dependencies` block.
Two dependency kinds are supported: `env` (environment variables and secrets) and `binaries` (version-checked executables on `PATH`).

Example:

```yaml
dependencies:
  env:
    PUBLIC_CLIENT_ID: abc123

    GITHUB_PAT:
      local: {}
      description: Personal GitHub PAT

    CONTEXT7_API_KEY:
      secret:
        provider: op
        ref: op://Example Vault/AI Tools/CONTEXT7_API_KEY

  binaries:
    - name: npx
      version:
        require: ~10.0.0
    - name: gh
      version:
        require: ^2.0.0
        get_cmd: gh --version
```

### Env rules

- only dependencies from selected artifacts are resolved
- `secret.provider` currently supports `op` only
- unresolved declared local vars emit warnings; MCP rendering uses empty placeholders for those vars so plan/apply can still complete (set values in `.env.ai-sync` for working MCP servers)
- `.env.ai-sync` is generated only when selected dependencies include `local` entries
- secret dependencies are never written to `.env.ai-sync`
- for MCP servers, `ai-sync` renders subprocess `env` from `dependencies.env`; use `inject_as` when several servers must expose the same subprocess name (for example `STRIPE_SECRET_KEY`) but need distinct dependency keys and secret refs; avoid top-level MCP `env` unless you need `${VAR}` interpolation outside `dependencies.env`

### Binary rules

- binary requirements are collected from all selected artifact kinds (agents, skills, commands, rules, MCP servers)
- identical declarations (same name + version constraint + get_cmd) across artifacts are deduplicated
- conflicting declarations (same name, different version or get_cmd) raise a collision error
- version constraints use `~X.Y.Z` (compatible within minor) or `^X.Y.Z` (compatible within major)
- each binary is checked by running `[name] --version` unless `get_cmd` overrides the command

## Project-local outputs

`ai-sync` manages project-local files such as:

- `.codex/*`
- `.cursor/*`
- `.gemini/*`
- `.claude/*`
- `.mcp.json`
- `CLAUDE.md`
- `.env.ai-sync`
- `.ai-sync/rules/`
- `.ai-sync/state/`
- `.ai-sync/sources/`
- `.ai-sync/last-plan.yaml`

It does not modify machine-global client config under `~/.codex`, `~/.cursor`, `~/.gemini`, or `~/.claude`.

When rules are selected, `ai-sync` writes rule files to `.ai-sync/rules/` and maintains a small managed link block in `AGENTS.md` instead of replacing the whole file.

You should usually cover these paths and `.ai-sync.local.yaml` with `.gitignore`, but `ai-sync` no longer blocks `plan` or `apply` when they are not ignored.

## Reliability rules

- Remote sources must be pinned.
- If two selected resources would write the same non-composable output, planning fails.
- Saved plans are invalidated when the project config or resolved source fingerprints change.

## Commands

```bash
ai-sync install
ai-sync plan
ai-sync apply [planfile]
ai-sync doctor
ai-sync uninstall [--apply]
```

## Architecture

### Dependency injection

- The composition root lives in `ai_sync.di`, with providers declared in `AppContainer`.
- The only runtime entrypoint is `cli.main()`, which calls `bootstrap_runtime()` to resolve `CommandHandlersService`.
- Command flows (`install`, `plan`, `apply`, `doctor`, `uninstall`) are implemented on service classes under `ai_sync.services`.
- Adapter boundaries (`filesystem`, `process runner`, `state store`) isolate side effects from orchestration logic.

### Universal artifact pipeline

All artifact kinds flow through one shared pipeline:

```
select → load → prepare (pre-runtime) → resolve RuntimeEnv → prepare (post-runtime) → collect artifacts → resolve ApplySpecs → apply & reconcile
```

- `ArtifactPreparationService` orchestrates preparation in two explicit phases: pre-runtime (validation, env dependency collection) and post-runtime (interpolation, rendering) after `RuntimeEnv` is resolved.
- The shared `PreparedArtifacts` boundary carries per-kind payloads (e.g. `PreparedMcpServer`) so downstream collectors, requirement checks, and plan builders all receive the same context.
- Kind-specific logic (MCP validation, env interpolation, rendered `env` synthesis) lives in `McpPreparationService`, called as a preparation hook inside the shared pipeline.

### Apply contract

Every artifact resolves into a sequence of `ApplySpec`, a union of two concrete types:

- `WriteSpec` — managed file writes (text markers, structured JSON/TOML/YAML keys).
- `EffectSpec` — managed side effects (pre-commit hook install/remove, file permission changes).

Both types are planned, confirmed, executed, and reversed through the same state-backed reconciliation engine in `ManagedOutputService` and `StateStore`.

### State management

- Managed state is persisted in `.ai-sync/state/state.json` with an explicit `STATE_VERSION`.
- Write baselines and effect baselines are tracked separately so `uninstall` can restore prior state for both files and side effects.
- Incompatible state from an older pipeline version is rejected with an actionable error directing the user to `ai-sync uninstall --apply` before reapplying.

## Testing

```bash
just test
```

DI-heavy tests should prefer provider overrides over module monkeypatching:

- Build a fresh container via `create_container()`.
- Override collaborators with `container.override_providers(...)`.
- Resolve the service under test from the container after overrides are applied.
