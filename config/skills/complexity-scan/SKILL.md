---
name: complexity-scan
description: Detect probable overengineering zones in TypeScript/NestJS/TypeORM codebases using evidence-based signals, prioritize domain logic, and propose low-risk refactor suggestions.
---

# Complexity Scan

Use this skill to identify probable overengineering zones and propose refactor suggestions using measurable signals.

## Quick Start

Run the bundled scanner against the repo root:

```bash
node <skill-path>/scripts/overengineering-scan.mjs \
  --repo /path/to/repo \
  --focus domain,infra,tests \
  --top 40 \
  --out /tmp/overengineering-scan.json
```

Optional Markdown output:

```bash
node <skill-path>/scripts/overengineering-scan.mjs \
  --repo /path/to/repo \
  --focus domain,infra,tests \
  --top 40 \
  --format md \
  --out /tmp/overengineering-scan.md
```

### Filters

- `--include`: comma-separated substrings; only paths containing one of these are scanned.
- `--exclude`: comma-separated substrings; paths containing any are skipped (in addition to defaults).

Example:

```bash
node <skill-path>/scripts/overengineering-scan.mjs \
  --repo /path/to/repo \
  --include src/ \
  --exclude src/core/,test/ \
  --top 30 \
  --out /tmp/overengineering-scan.json
```

## Workflow

1. Run the scanner and capture the top outliers. Prefer `domain` first, then `infra`, then `tests`.
2. For each outlier, open the file and validate signals with concrete evidence (lines, symbols, usage).
3. Apply the rubric below to decide if it is overengineered or justified.
4. Provide non-breaking refactor suggestions with clear impact and confidence.

## Overengineering Rubric (Evidence First)

Flag as probable overengineering when **multiple** signals appear:

- Large function/method with high branching and deep nesting.
- Many dependencies injected into a class without clear need.
- Layering/indirection chains for a single simple responsibility.
- Broad generic/type machinery for narrow, single-use flows.
- Heavy configuration or ceremony to achieve a straightforward behavior.

Counter-signals (do not flag without caution):

- Proven reuse across multiple modules.
- Clear extension points already in active use.
- Compliance or cross-cutting constraints that demand abstraction.

## Output Format

For each zone, report:

1) Location (file path + symbol)
2) Evidence (metrics + specific constructs)
3) Why overengineered (1–2 sentences)
4) Impact (maintenance, debugging, onboarding, perf)
5) Safer refactor (keep semantics intact)
6) Confidence (low/med/high)

## Notes

- If the repo lacks `node_modules`, the scanner may not load TypeScript. In that case, run `npm install` or skip the scanner and do a manual evidence-based review.
- Keep suggestions aligned with project conventions and avoid breaking changes.
