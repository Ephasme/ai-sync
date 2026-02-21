---
name: git-absorb-commit-range
description: Split a source git commit into hunks, assign each hunk to the best target commit within a provided revision range using blame hit counts, then create fixup commits and autosquash them into their targets. Use when you need to absorb or redistribute a commit's changes across its parent commits inside a specific git rev range (e.g., base..HEAD).
---

# Git Absorb Commit Range

## Overview

Absorb a single source commit into earlier commits in a range by splitting it into hunks, selecting the best target commit per hunk via blame counts, then fixup/autosquashing those hunks into place with safety checks and conflict aborts.

## Inputs

- `rev_range`: A git range like `base..<range-end>` where the target commits live.
- `source_commit`: The commit to absorb (must be after the range end on the same branch).
- `source_commit` must not be the base commit or the range end.

## Workflow (Preferred)

1. Ensure a clean working tree and a linear history from the base to `HEAD` (no merges).
2. Ensure the range base is an ancestor of the range end, and the range end is an ancestor of the source commit.
3. Ensure `HEAD` is at or after the source commit.
4. Run `scripts/absorb-commit-into-range.py`.
4. If any conflict or failure occurs, the script aborts and restores the original state.

## Scripts

### `scripts/absorb-commit-into-range.py`

End-to-end pipeline. It:

1. Splits the source commit into hunks with `split-commit-hunks.py`.
2. Assigns each hunk to the best target commit in the range using `update-hunk-targets.py`.
3. Drops the source commit from history.
4. Applies each hunk and creates `--fixup` commits.
5. Runs `git rebase -i --autosquash` to absorb fixups into targets, then drops any empty commits.
6. Aborts and restores if any step fails.

Usage (source after range end):

```bash
python3 /Users/loup/.codex/skills/git-absorb-commit-range/scripts/absorb-commit-into-range.py base..HEAD~1 <source-commit>
```

Options:

- `--dry-run`: compute targets and print summary only; do not rewrite history
- `--allow-merges`: allow merge commits and use `--rebase-merges`
- `--min-blame-hits <n>`: minimum blame hits required for a target
- `--min-lines <n>`: minimum hunk size (max of old/new counts) to consider
- `--fallback skip|parent`: fallback target when blame is weak
- `--split-script <path>`: override the split script path
- `--update-script <path>`: override the target assignment script path
- `--log-file <path>`: override log file location (default: `.git/absorb-commit-into-range.log`)
- `--csv <path>`: write/read hunk CSV to a specific path
- `--keep-temp`: keep the temp directory for inspection

### `scripts/split-commit-hunks.py`

Splits a commit into hunks and writes a CSV. Requires `pygit2`.

```bash
python3 /Users/loup/.codex/skills/git-absorb-commit-range/scripts/split-commit-hunks.py <commit> --out ./out/hunks.csv
```

Options:

- `--cwd <path>`: run against a specific repository path

### `scripts/update-hunk-targets.py`

Assigns each hunk a target commit by blame hits within the range. Use `--exclude` to avoid targeting the source commit.

```bash
python3 /Users/loup/.codex/skills/git-absorb-commit-range/scripts/update-hunk-targets.py base..HEAD hunks.csv --exclude <source-commit>
```

Options:

- `--min-blame-hits <n>`: minimum blame hits required for a target
- `--min-lines <n>`: minimum hunk size (max of old/new counts) to consider
- `--fallback skip|parent`: fallback target when blame is weak
- `--exclude-range <rev-range>`: exclude a range of commits from targeting

Notes:

- Populates `blame-top-3` with the top blame candidates for debugging.
- If blame is weak or missing (including binary patches), it may fall back to the most recent commit in the range that touched the file.
- Binary patches are supported by encoding patch data in the CSV as `base64:<payload>` and decoding during apply.

## Safety And Conflict Handling

- If there is any conflict or a command fails, stop immediately and restore the repo state.
- The pipeline creates a backup branch `absorb-backup-<timestamp>` before rewriting history.
- The pipeline requires a clean working tree and a linear range (no merges).
- On failure, the pipeline runs `git reset --hard <orig-head>` after restoring refs to ensure a clean working tree.
- The pipeline appends logs to `.git/absorb-commit-into-range.log`.

## Notes

- Ensure `pygit2` is installed for `split-commit-hunks.py`.
- If some hunks cannot be assigned to a target commit, abort and inspect the CSV with `--keep-temp`.
- Avoid running this on ranges with merges unless you extend the script to handle `--rebase-merges`.
- The hunk CSV may contain `base64:`-prefixed patch entries for binary changes; keep them intact if you edit the CSV.
