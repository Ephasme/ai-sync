---
name: git-safe-rebase
description: Safely rebase the current git branch onto origin/dev using a strict, repeatable workflow (stash, update dev, conflict scouting, plan, rebase) and produce an evidence-backed conflict report. Use when a user asks to rebase on origin/dev or wants a cautious rebase process with conflict planning.
---

# Git Safe Rebase

## Overview

Perform a guarded rebase of the current branch onto origin/dev. Require a pre-merge conflict scouting step and a written conflict-resolution plan before rebasing. Produce a concise, evidence-backed report with conflicts, hashes, and confidence.

## Workflow (follow in order)

1. Preconditions
- Run `git status --short`.
- If not clean, stash everything: `git stash push -u -m "codex: rebase prep"`.
- Record whether a stash was created.

2. Update dev baseline
- `git fetch --all`
- `git checkout dev`
- `git pull`
- `git checkout -` (return to original branch)
- Record current branch name and pre-rebase HEAD hash.

3. Study current branch
- `git log --oneline --decorate -n 50`
- `git diff origin/dev...HEAD --stat`
- Summarize intended features/goals in one or two sentences.

4. Conflict scouting (dummy merge)
- `git merge --no-commit --no-ff origin/dev`
- If conflicts appear, do not resolve.
- Write a conflict-resolution plan (temporary file in a temp dir) that lists:
  - Each conflicting file
  - Intended resolution strategy
  - Evidence supporting the plan (diff/log references)
- Review non-conflicting changes for consistency.
- Abort the merge: `git merge --abort`.

5. Rebase using the plan
- `git rebase origin/dev`
- Resolve conflicts strictly per the written plan.
- If new conflicts appear not in the plan, update the plan and continue.
- If conflicts represent incompatible concepts/features (not just code), stop and refuse to rebase, explaining why.
- After the rebase completes, delete the temporary plan file.

## Rules

- No guessing. If any ambiguity exists, stop and ask questions.
- Any code involving external libraries must be verified with up-to-date official docs (Context7 first; fallback to web if Context7 is unavailable).
- Refuse to rebase if conflicts represent incompatible concepts/features.

## Required output

- Summary of resolved conflicts: strategy used, reasoning, and verifiable evidence.
- From and to branch/hash, and number of conflicts resolved.
- Confidence estimate that the rebase did not introduce errors.
- Note whether a stash was created and whether it remains un-applied.

## Output style

Be concise, evidence-backed, and explicit about any assumptions.
