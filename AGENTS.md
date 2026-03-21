# AI Assistant Instructions

This file defines project-level guidance for coding assistants working in this repository.

## Project Goal

`ai-sync` keeps AI tooling configuration project-scoped, reproducible, and safe across supported clients (Codex, Cursor, Gemini, Claude Code).
It syncs reusable resources from source repos into local project outputs so teams share the same assistant behavior without relying on machine-global setup.

## Project structure

- In `services` folder please write the services only, one file equals one service and the name of the class and the file should be consistent.

## Vocabulary

- **Source**: a local or remote repository that provides reusable AI resources.
- **Manifest**: `.ai-sync.yaml` (or `.ai-sync.local.yaml`) that declares sources and selected resources.
- **Scoped reference**: `<sourceAlias>/<resourceId>` identifier used to select a resource from a source.
- **Artifacts**: normalized internal representation of selected resources before writing files.
- **Prepared artifacts**: shared boundary (`PreparedArtifacts`) produced by the preparation pipeline, carrying per-kind payloads for downstream collectors and plan builders.
- **Plan**: computed action set (writes/deletes/updates/effects) generated from current manifest + sources.
- **Apply**: execution step that performs the planned writes and effects in the project.
- **ApplySpec**: common contract for all managed operations — `WriteSpec` for file writes, `EffectSpec` for side effects (hook install, permission changes).
- **Managed outputs**: files/directories owned or partially managed by `ai-sync` (for example `.codex/`, `.cursor/`, `.gemini/`, `.claude/`, `.ai-sync/*`, and selected managed blocks in markdown files).

## Python Coding Best Practices (Consensus)

- MUST preserve readability and consistency: simple control flow, clear names, and small focused functions.
- MUST use type hints on public interfaces and important internal boundaries.
- MUST isolate side effects (filesystem, network, env, subprocess) at boundaries; keep core logic testable.
- SHOULD add docstrings for public modules, classes, and functions, including behavior and failure modes.
- SHOULD use structured logging for diagnostics in reusable code.
- MUST raise precise exceptions with actionable messages and fail fast on invalid input.

## CLI Architecture Best Practices (Consensus)

- MUST keep a small `main()` entrypoint and modular command handlers.
- MUST return explicit exit codes: `0` on success, non-zero on failure.
- MUST write user-facing errors to `stderr`.
- MUST provide clear `--help` and `--version` behavior.
- SHOULD use subcommands for distinct operations (`plan`, `apply`, `doctor`, etc.) and keep argument names stable.
- SHOULD keep CLI UX predictable: options first, `--` delimiter support, and consistent flag naming.

## DI Architecture Expectations

- MUST keep runtime wiring in `ai_sync.di` (`AppContainer` + `bootstrap_runtime`) and avoid ad-hoc composition in feature modules.
- MUST expose orchestration behavior through service classes in `ai_sync.services`, not module-level runtime wrapper functions.
- SHOULD keep module-level helpers stateless where possible; stateful orchestration belongs on injected services.
- MUST keep `cli.main()` as the only runtime entrypoint that resolves top-level handlers from the container.
- MUST prefer provider overrides (`container.override_providers(...)`) in tests over monkeypatching module runtime functions.

## Core Expectations

- Keep changes minimal, targeted, and reversible.
- Prefer correctness and explicitness over clever shortcuts.
- Preserve existing behavior unless a change request explicitly asks for behavioral changes.
- Add or update tests when behavior changes.

## Keep Everything Greenfield

- Prefer replacing and deleting superseded code over compatibility shims, aliases, fallback paths, or parallel implementations.
- Remove stale references (code, tests, fixtures, comments, and docs) in the same change whenever practical.
- Do not leave dead code behind: remove unused helpers, obsolete branches, stale flags, and commented-out legacy blocks.
- Keep tests aligned with current behavior and naming; avoid preserving historical behavior unless explicitly required.

## Workflow

- Use `just` commands in first intention for local setup, linting, typechecking, tests, and release preparation instead of calling the underlying tools directly.
- Run `just install` when setting up the repo or refreshing the local toolchain; it installs dev dependencies and registers the `pre-commit` hook.
- Before committing, prefer running the relevant `just` checks first: `just lint`, `just typecheck`, and `just test`.
- Let the installed `pre-commit` hook run on normal `git commit`; do not bypass it unless the user explicitly requests that.
- Use `just fix` for safe Ruff autofixes before re-running checks.
- Use `just lock` when updating dependency lock state, and use `just release <version>` for the documented release flow instead of manually reproducing those steps.
- Run relevant tests for touched areas when possible.
- Keep docs aligned with behavior and CLI output.
- Avoid committing secrets, tokens, or machine-local configuration.

## ai-sync Managed Rules

`ai-sync` may append a managed rules index block to this file.
Do not manually edit content inside managed marker blocks.

<!-- BEGIN ai-sync:rules-index -->
## ai-sync Rules (managed)

You MUST read and follow ALL rules listed below:

- [commit-conventions](.ai-sync/rules/sherpas-dev-commit-conventions.md)
<!-- END ai-sync:rules-index -->
