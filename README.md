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

mcp-servers:
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
├── prompts/
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
├── mcp-servers/
│   └── <server-id>/
│       └── artifact.yaml
├── requirements.yaml
└── env.yaml
```

### Resource ids

- Agents come from `prompts/<name>/artifact.yaml` plus `prompts/<name>/prompt.md` and are referenced as `<alias>/<name>`.
- Skills come from `skills/<name>/artifact.yaml` plus `skills/<name>/prompt.md` and are referenced as `<alias>/<name>`.
- Commands come from `commands/**/<name>/artifact.yaml` plus sibling `prompt.md` and are referenced as `<alias>/<relative-path>`.
- Rules come from `rules/<name>/artifact.yaml` plus `rules/<name>/prompt.md` and are referenced as `<alias>/<name>`.
- MCP servers come from `mcp-servers/<server-id>/artifact.yaml` and are referenced as `<alias>/<server-id>`.

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

## Secrets

Secrets stay as references in source repos and project config. `ai-sync` resolves them locally and can generate a project-local `.env.ai-sync` file when needed.

Example `env.yaml`:

```yaml
CONTEXT7_API_KEY:
  value: op://Example Vault/AI Tools/CONTEXT7_API_KEY
EXA_API_KEY:
  value: op://Example Vault/AI Tools/EXA_API_KEY
PUBLIC_CLIENT_ID:
  value: abc123
GITHUB_PAT:
  scope: local
  description: Personal GitHub PAT
```

Rules:

- plan artifacts never store plaintext secret values
- plans show secret-backed outputs in redacted form
- apply fails if required secret values cannot be resolved

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

Runtime orchestration is class-based and dependency-injected:

- The composition root lives in `ai_sync.di`, with providers declared in `AppContainer`.
- The only runtime entrypoint is `cli.main()`, which calls `bootstrap_runtime()` to resolve `CommandHandlersService`.
- Command flows (`install`, `plan`, `apply`, `doctor`, `uninstall`) are implemented on service classes under `ai_sync.services`.
- Adapter boundaries (`filesystem`, `process runner`) isolate side effects from orchestration logic.

## Testing

```bash
python -m pytest tests
```

DI-heavy tests should prefer provider overrides over module monkeypatching:

- Build a fresh container via `create_container()`.
- Override collaborators with `container.override_providers(...)`.
- Resolve the service under test from the container after overrides are applied.
