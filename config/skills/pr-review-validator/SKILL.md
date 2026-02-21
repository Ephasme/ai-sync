---
name: pr-review-validator
description: Fetch unresolved GitHub PR review threads, write them to a temporary file, and produce an evidence-backed triage report (severity/validity, fixes, and DO/DON'T recommendation). Use when asked to gather unresolved PR comments (by URL or number) and assess each against the local codebase or official documentation.
---

# PR Review Validator

## Overview

Fetch unresolved PR review threads from GitHub, write them to a temporary JSON file, and generate a strict, evidence-backed triage report with severity/validity, targeted fixes or answers, and a DO/DON'T recommendation.

## Workflow

### 1) Collect PR context

- Accept a **full PR URL only** (required). PR numbers alone are not allowed.
- Ensure GitHub CLI (`gh`) is installed and authenticated (`gh auth status`) with read access to the repo.

### 2) Fetch unresolved review threads

Use the bundled script (via `gh api graphql`) to retrieve review threads and write them to a temp file:

```bash
python3 <skill-path>/scripts/fetch_unresolved_pr_comments.py \
  --pr "https://github.com/OWNER/REPO/pull/123"
```

Optional flags:

- `--out /tmp/path.json` to control the output file.
- `--include-outdated` to keep threads marked as outdated.
- `--include-resolved` to keep resolved threads (not typical for triage).

**Output:** JSON containing PR metadata and an array of unresolved threads with comment bodies, authors, and file location fields.

Assumption (state explicitly in results if relevant): This skill focuses on review threads. Top-level PR issue comments are not “resolvable”; include them only if the user explicitly requests them.

### 3) Verify each comment against the codebase

For each thread:

- Open `path` at `line` (or `startLine`/`originalLine` if needed) in the working tree.
- Confirm whether the code still matches the comment context (use `git blame`, `git show`, or `rg` for historical context).
- If the comment references external behavior or APIs, use Context7 first; if unavailable, warn and fall back to web search; if still unavailable, mark INCONCLUSIVE.

### 4) Assign validity and severity

**Validity**

- `VALID`: Evidence in code/tests/docs confirms the issue.
- `INVALID`: Evidence shows the concern is not applicable or already addressed.
- `INCONCLUSIVE`: Missing or conflicting evidence; explicitly call out the gap.

**Severity**

- `CRITICAL`: Security, data loss, payment/financial loss, or widespread outage risk.
- `MAJOR`: User-facing correctness issues, crashes, or significant service degradation.
- `MINOR`: Edge cases, performance concerns, or maintainability defects.
- `TRIVIAL`: Style nits or low-impact readability concerns.

### 5) Produce the report

For each comment, provide:

- Direct comment link.
- Author.
- Target file + line.
- Severity and validity, each with evidence.
- Proposed fix (if bug) or direct answer (if question).
- A surgical fix prompt (minimum-change, localized, no collateral impact).
- A one-line conclusion: `DO` or `DON'T`.

**Evidence requirements**

- Each claim must be backed by a concrete proof: file path + line, test output, or official documentation.
- Clearly label any assumptions or hypotheses.
- If you cannot produce proof, mark the item INCONCLUSIVE.

## Report Template

```markdown
### Comment <n>

- Link: <comment-url>
- Author: <login>
- Target: <file-path>:<line>
- Severity: <CRITICAL|MAJOR|MINOR|TRIVIAL>
  - Evidence: <proofs with file paths/lines or official docs>
- Validity: <VALID|INVALID|INCONCLUSIVE>
  - Evidence: <proofs with file paths/lines or official docs>
- Proposed fix / answer: <concise fix or response>
- Surgical fix prompt: <single-sentence, minimal-change instruction>
- Conclusion: DO or DON'T
```

## Script Notes

The script relies on GitHub’s GraphQL schema fields for review threads (`isResolved`, `isOutdated`, `path`, `line`, `originalLine`, `startLine`, `originalStartLine`) and review comments (`url`, `resourcePath`, `bodyText`, `author`). If the schema differs (e.g., older GitHub Enterprise), reduce queried fields and mark missing data as INCONCLUSIVE.
