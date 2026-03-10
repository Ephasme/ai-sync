# `ai-sync`

`ai-sync` synchronizes shared AI tooling artifacts into a project-local setup for Codex, Cursor, and Gemini.

The current workflow is:

1. Install `ai-sync` once on the machine.
2. Write a project `.ai-sync.yaml`.
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

Optional task runner:

```bash
brew install just
just install
just test
```

## Machine bootstrap

`install` is the only machine-level setup step. It writes `~/.ai-sync/config.toml` for auth/bootstrap settings such as 1Password account selection.

```bash
ai-sync install --op-account NAME
```

You can also authenticate with `OP_SERVICE_ACCOUNT_TOKEN`.

## Project workflow

### 1. Write `.ai-sync.yaml`

Projects declare their config sources explicitly and select resources by fully scoped ids.

Example:

```yaml
sources:
  company:
    source: github.com/acme/company-ai-sync
    version: v1.2.0
  frontend:
    source: ../frontend-ai-sync

agents:
  - company/senior-software-engineer

skills:
  - company/code-review
  - frontend/react-review

commands:
  - company/session-summary.md

rules:
  - company/commit-conventions

mcp-servers:
  - company/context7

settings:
  mode: normal
  subagents: true
```

Notes:

- Remote sources must be pinned with `version`.
- Local path sources are allowed, but they are less portable than pinned remote sources.
- Every selected resource must be scoped as `<sourceAlias>/<resourceId>`.
- `.ai-sync.local.yaml` is no longer part of the main workflow.

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
├── skills/
├── commands/
├── rules/
├── mcp-servers.yaml
├── requirements.yaml
└── .env.ai-sync.tpl
```

### Resource ids

- Agents come from `prompts/<name>.md` and are referenced as `<alias>/<name>`.
- Skills come from `skills/<name>/SKILL.md` and are referenced as `<alias>/<name>`.
- Commands come from `commands/**/<name>.<ext>` and are referenced as `<alias>/<relative-path>`.
- Rules come from `rules/<name>.md` and are referenced as `<alias>/<name>`.
- MCP servers come from keys in `mcp-servers.yaml` and are referenced as `<alias>/<server-id>`.

## Secrets

Secrets stay as references in source repos and project config. `ai-sync` resolves them locally and can generate a project-local `.env.ai-sync` file when needed.

Example `.env.ai-sync.tpl`:

```text
CONTEXT7_API_KEY=op://Employee/AI Tools/CONTEXT7_API_KEY
EXA_API_KEY=op://Employee/AI Tools/EXA_API_KEY
PUBLIC_CLIENT_ID=abc123
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
- `.env.ai-sync`
- `.ai-sync/state/`
- `.ai-sync/sources/`
- `.ai-sync/last-plan.yaml`

It does not modify machine-global client config under `~/.codex`, `~/.cursor`, or `~/.gemini`.

Make sure these paths are covered by `.gitignore`.

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

Legacy note:

- `ai-sync import` remains available only as a transitional helper.
- `ai-sync init` is deprecated in this workflow.

## Testing

```bash
python -m pytest tests
```
