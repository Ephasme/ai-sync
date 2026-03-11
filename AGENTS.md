# AGENTS.md

This workspace is a multi-project `ai-sync` working area, not a single git repo. Run git commands from the relevant subproject directory.

## Workspace Map

- `ai-sync-core/`: main Python package and CLI implementation.
- `ai-sync-config-example/`: reference `ai-sync` source repo template.
- other `ai-sync-config-*` directories in this workspace: concrete config repos; treat them as content/config unless the task says otherwise.

## Working In `ai-sync-core`

- Use Python `>=3.11`.
- Install dev dependencies with `poetry sync --with dev`.
- Preferred commands:
  - `just test`
  - `just typecheck`
  - `just lint`
  - `just fix`
- Application code lives in `src/ai_sync/`.
- Tests live in `tests/`.
- Match the existing style: typed Python, small focused functions, and targeted behavior changes.
- Add or update tests when changing CLI behavior, planning logic, syncing logic, or manifest validation.

## Python Best Practices

- Prefer explicit type hints on public functions, dataclasses, and complex locals when they improve readability.
- Use `pathlib.Path` for filesystem work instead of stringly-typed path manipulation.
- Keep functions small and side effects obvious; extract pure helpers for parsing, validation, and planning logic.
- Validate external input at boundaries and fail with actionable error messages.
- Prefer standard library solutions unless a dependency clearly simplifies the design.
- Avoid hidden global state; pass dependencies such as paths, display objects, or resolved config explicitly.
- Preserve existing style around structured models, dataclasses, and `pydantic` validation rather than introducing parallel patterns.

## Architecture Best Practices

- Keep the CLI layer thin: argument parsing and user interaction in CLI modules, business logic in focused library modules.
- Separate concerns cleanly: config loading, source resolution, planning, rendering, and apply/sync steps should stay distinct.
- Isolate filesystem, subprocess, network, and secret-resolution code behind small functions so behavior is easier to test.
- Prefer deterministic, idempotent operations; planning should be predictable from inputs and apply should avoid surprising side effects.
- Extend existing modules and abstractions before adding new cross-cutting patterns or frameworks.
- When a change touches multiple layers, keep interfaces narrow and document invariants in code with concise names or short comments where needed.

## Keep It Greenfield

- Prefer replacing and deleting old code over keeping compatibility shims, aliases, fallback paths, or parallel implementations.
- When behavior, APIs, files, or names are removed, remove all code, tests, fixtures, comments, and docs that reference the old behavior in the same change when practical.
- A refactor or behavior change is not complete until stale references have been actively searched for and removed across implementation code, tests, fixtures, and documentation.
- Do not leave dead code behind: remove unused functions, stale helpers, obsolete branches, commented-out code, unused flags, and unreachable paths instead of marking them for later cleanup.
- Tests should describe current behavior only; do not keep references to removed commands, modules, error messages, or historical behavior unless the task is explicitly about a migration.
- Avoid "legacy" preservation by default. If backward compatibility is truly required, make it explicit, minimal, and time-bounded.
- If a new design supersedes an old one, migrate callers and delete the superseded path rather than keeping both architectures alive.
- Prefer renaming or rewriting tests and helpers to match current concepts exactly instead of carrying outdated names forward.

## Working In Config Repos

- Source repo artifacts follow the documented layout: `prompts/`, `skills/<name>/SKILL.md`, `commands/`, optional `rules/`, optional `mcp-servers/<server-id>/server.yaml`, optional `requirements.yaml`, and optional `.env.ai-sync.tpl`.
- Keep artifact identifiers stable unless a rename is explicitly requested.
- Prompt metadata is optional and only supports fields that current runtime consumes: `slug`, `name`, and `description`.
- Keep secrets as references in `.env.ai-sync.tpl`; never replace them with plaintext credentials.

## Safety And Scope

- Do not manually edit generated or synced client outputs unless the task is specifically about them: `.cursor/*`, `.codex/*`, `.gemini/*`, `.ai-sync/state/`.
- Prefer minimal diffs and targeted validation over broad refactors.
- If a task spans multiple subprojects, be explicit about which directory each change belongs to.
