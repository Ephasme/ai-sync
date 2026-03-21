# Skills in ai-sync — authoring guidelines

This document is for **maintainers of ai-sync source repos** (config catalogs). It ties the open **Agent Skills** format to how `ai-sync` loads bundles, renders **`SKILL.md`**, and writes per-client outputs.

Project workflow, manifest keys, and full source layout: see the root [README](../README.md).

## How ai-sync models skills

- The **manifest** lists scoped ids: `skills: [<sourceAlias>/<resourceId>]` (same pattern as agents, rules, etc.).
- Each skill lives in the source repo under `skills/<resourceId>/` with **`artifact.yaml`** + **`prompt.md`** (and optional **`files/`**).
- `ai-sync` **does not** store `SKILL.md` in the source repo; it **generates** it at apply time from metadata + `prompt.md`.
- Apply writes managed outputs under **each enabled client**, e.g. `.cursor/skills/…`, `.claude/skills/…`, `.codex/skills/…`, `.gemini/skills/…` (see [README](../README.md) “Project-local outputs”).

Implementation reference: `SkillArtifactService` in `src/ai_sync/services/skill_artifact_service.py`.

## Source bundle layout

```text
<source-repo>/skills/<resourceId>/
├── artifact.yaml    # metadata (+ optional dependencies.env / dependencies.binaries)
├── prompt.md        # markdown body of the skill (required)
└── files/           # optional; synced into the skill root without the `files/` prefix
    └── ...
```

Rules that match the loader (`ArtifactBundleService`):

- **`dependencies`** in `artifact.yaml` is parsed for env resolution; it is **not** copied into `SKILL.md` frontmatter.
- Inline **`prompt`** in `artifact.yaml` is **forbidden**; body text must live in `prompt.md`.
- **Required metadata keys** for skills: **`name`**, **`description`** (enforced when the bundle is loaded).

## What becomes `SKILL.md`

`ai-sync` builds:

1. **YAML frontmatter** — a dump of **every key** still present in `artifact.yaml` after `dependencies` is removed (so keep keys limited to what agents should see: standard skill fields plus intentional extras).
2. **Body** — the full contents of `prompt.md`.

Optional Agent Skills frontmatter fields (when you want them in the rendered file) include `license`, `compatibility`, `metadata`, and client-specific keys such as Cursor’s `disable-model-invocation`. See the [open specification](https://agentskills.io/specification.md).

## Output directory and `name`

For each client, the skill is written to:

```text
.<client>/skills/<sourceAlias>-<kebab>/
```

where `<kebab>` is derived from the **last segment** of `skills/<resourceId>/` (underscores and spaces become hyphens, lowercased). Example: source alias `company`, folder `skills/db-read-only-access/` → `.cursor/skills/company-db-read-only-access/`.

The [Agent Skills spec](https://agentskills.io/specification.md) expects the frontmatter **`name`** to match the **parent folder** of `SKILL.md`. With ai-sync, that folder is always **prefixed** with the manifest source alias. If `artifact.yaml` sets `name` to only the resource id (e.g. `db-read-only-access`), it may **differ** from the on-disk folder (`company-db-read-only-access`). Many agents still work; for strict alignment, set `name` to the **actual output folder basename** for your intended alias, or accept the mismatch and test in target clients.

## Bundled files under `files/`

- Paths are preserved relative to `files/`, e.g. `files/scripts/run.sh` → `scripts/run.sh` next to `SKILL.md`.
- **`.json`**, **`.yaml` / `.yml`**, and **`.toml`** files under `files/` are **parsed** and written through structured merge logic, not always as a single literal file copy. Prefer **`.md`**, **`.py`**, **`.sh`**, or other non-structured extensions when you need a verbatim asset unless you intend structured writes.
- Skip patterns under `files/` include `.venv`, `node_modules`, `__pycache__`, `.git`, `.DS_Store`.

## `description` and body (content quality)

The generated skill behaves like any other Agent Skill: agents typically load **all skills’ metadata** up front, then **`SKILL.md`** when relevant.

Follow ecosystem guidance (concise body, third-person **`description`**, **what + when**, trigger keywords, progressive disclosure via linked files under `files/`):

| Topic                     | URL                                                                                                                                                                                                                                                                                                                              |
| ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Specification             | [agentskills.io/specification.md](https://agentskills.io/specification.md)                                                                                                                                                                                                                                                       |
| Authoring                 | [Best practices](https://agentskills.io/skill-creation/best-practices.md), [Evaluating skills](https://agentskills.io/skill-creation/evaluating-skills.md), [Optimizing descriptions](https://agentskills.io/skill-creation/optimizing-descriptions.md), [Using scripts](https://agentskills.io/skill-creation/using-scripts.md) |
| Claude                    | [Overview](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview), [Best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)                                                                                                                                       |
| Cursor                    | [Agent Skills](https://cursor.com/docs/context/skills)                                                                                                                                                                                                                                                                           |
| Validate a rendered skill | [skills-ref](https://github.com/agentskills/agentskills/tree/main/skills-ref) on the **output** tree after `apply`                                                                                                                                                                                                               |

Practical content rules (same as hand-authored skills):

- Put only **non-obvious** procedural and domain knowledge in `prompt.md`; skip generic tutorials.
- Match **specificity to risk** (flexible guidance vs exact commands for fragile steps).
- Prefer **one default** tool or approach; mention alternates briefly.
- Link bundled docs from `prompt.md` with **relative paths** and **one level of indirection** from `SKILL.md` where possible (see agentskills.io best practices).
- Use **forward slashes** in paths.

## Dependencies (`dependencies.env` and `dependencies.binaries`)

Skills support the same `dependencies` blocks as other bundles: `dependencies.env` for environment variables and secrets, and `dependencies.binaries` for version-checked executables. See [README](../README.md) “Artifact dependencies”. Declared dependencies feed plan/apply resolution; they are **not** embedded in `SKILL.md`.

## Security

Skills can instruct agents to execute tools and bundled code. Only sync sources you **trust**; audit `prompt.md`, `artifact.yaml`, and everything under `files/` the same way you would third-party automation.

## Checklist (ai-sync + Agent Skills)

- [ ] `skills/<resourceId>/artifact.yaml` includes **`name`** and **`description`**; no inline `prompt`.
- [ ] `prompt.md` exists and reads well as the **body** after frontmatter.
- [ ] Frontmatter keys are deliberate (everything except `dependencies` is echoed into `SKILL.md`).
- [ ] Bundled paths under `files/` use the extensions you intend (structured vs literal).
- [ ] Consider whether **`name`** should match `.<client>/skills/<sourceAlias>-<kebab>/` for strict clients.
- [ ] After `apply`, spot-check generated `SKILL.md` under a target `.cursor` / `.claude` / … tree.
