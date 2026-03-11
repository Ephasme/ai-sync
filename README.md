# `ai-sync`

`ai-sync` synchronizes shared AI tooling artifacts into a project-local setup for Codex, Cursor, and Gemini.

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
├── skills/
├── commands/
├── rules/
├── mcp-servers/
│   └── <server-id>/
│       └── server.yaml
├── requirements.yaml
└── .env.ai-sync.tpl
```

### Resource ids

- Agents come from `prompts/<name>.md` and are referenced as `<alias>/<name>`.
- Skills come from `skills/<name>/SKILL.md` and are referenced as `<alias>/<name>`.
- Commands come from `commands/**/<name>.<ext>` and are referenced as `<alias>/<relative-path>`.
- Rules come from `rules/<name>.md` and are referenced as `<alias>/<name>`.
- MCP servers come from `mcp-servers/<server-id>/server.yaml` and are referenced as `<alias>/<server-id>`.

## Secrets

Secrets stay as references in source repos and project config. `ai-sync` resolves them locally and can generate a project-local `.env.ai-sync` file when needed.

Example `.env.ai-sync.tpl`:

```text
CONTEXT7_API_KEY=op://Example Vault/AI Tools/CONTEXT7_API_KEY
EXA_API_KEY=op://Example Vault/AI Tools/EXA_API_KEY
PUBLIC_CLIENT_ID=abc123
```

Rules:

- plan artifacts never store plaintext secret values
- plans show secret-backed outputs in redacted form
- apply fails if required secret values cannot be resolved

## Project-local outputs

`ai-sync` manages project-local files such as:

- `AGENTS.generated.md`
- `.codex/*`
- `.cursor/*`
- `.gemini/*`
- `.env.ai-sync`
- `.ai-sync/state/`
- `.ai-sync/sources/`
- `.ai-sync/last-plan.yaml`

It does not modify machine-global client config under `~/.codex`, `~/.cursor`, or `~/.gemini`.

When rules are selected, `ai-sync` writes the merged content to `AGENTS.generated.md` and maintains a small managed link block in `AGENTS.md` instead of replacing the whole file.

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

## Testing

```bash
python -m pytest tests
```
