#!/usr/bin/env python3
import argparse
import csv
import os
import re
import subprocess
import sys
import tempfile
from typing import Dict, List, Optional, Sequence, Set, Tuple


def usage() -> None:
    prog = os.path.basename(sys.argv[0])
    print(f"Usage: {prog} <rev-range> <input.csv> [output.csv]", file=sys.stderr)
    print(f"Example: {prog} dev..HEAD hunks.csv", file=sys.stderr)
    print(f"Example: {prog} dev..HEAD hunks.csv --exclude <commit>", file=sys.stderr)
    print(f"Example: {prog} dev..HEAD hunks.csv --min-blame-hits 3 --min-lines 5", file=sys.stderr)
    print(f"Example: {prog} dev..HEAD hunks.csv --exclude-range base..HEAD~2", file=sys.stderr)


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("rev_range")
    parser.add_argument("input_path")
    parser.add_argument("output_path", nargs="?")
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--exclude-range", action="append", default=[])
    parser.add_argument("--min-blame-hits", type=int, default=1)
    parser.add_argument("--min-lines", type=int, default=1)
    parser.add_argument("--fallback", choices=["skip", "parent"], default="skip")
    parser.add_argument("-h", "--help", action="help", default=argparse.SUPPRESS)
    return parser.parse_args(argv)


def run_git(
    args: Sequence[str],
    *,
    check: bool = True,
    cwd: Optional[str] = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=cwd,
    )


def validate_range(rev_range: str) -> None:
    result = run_git(["rev-list", rev_range], check=False)
    if result.returncode != 0:
        raise ValueError(f"invalid revision range: {rev_range}")


def resolve_commit(commitish: str) -> str:
    result = run_git(["rev-parse", commitish], check=False)
    if result.returncode != 0:
        raise ValueError(f"invalid commit: {commitish}")
    return result.stdout.strip()


def resolve_commit_optional(commitish: str) -> Optional[str]:
    result = run_git(["rev-parse", "--verify", commitish], check=False)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def normalize_path(path: str) -> str:
    path = path.strip()
    if path == "/dev/null" or not path:
        return ""
    if path.startswith("a/") or path.startswith("b/"):
        return path[2:]
    return path


def extract_file_path(row: Dict[str, str], hunk_text: str) -> str:
    target_file = row.get("target-file", "").strip()
    if target_file:
        return target_file

    commit_name = row.get("commit-name", "")
    parts = commit_name.rsplit(" | ", 2)
    if len(parts) == 3:
        file_part = parts[1].strip()
        if file_part:
            return normalize_path(file_part)

    for line in hunk_text.splitlines():
        if line.startswith("+++ "):
            return normalize_path(line[4:])
        if line.startswith("--- "):
            return normalize_path(line[4:])
        if line.startswith("diff --git "):
            diff_parts = line.split()
            if len(diff_parts) >= 4:
                return normalize_path(diff_parts[3])

    return ""


def parse_hunk_header(hunk_text: str) -> Optional[Tuple[int, int, int, int]]:
    for line in hunk_text.splitlines():
        match = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
        if match:
            old_start = int(match.group(1))
            old_count = int(match.group(2) or "1")
            new_start = int(match.group(3))
            new_count = int(match.group(4) or "1")
            return old_start, old_count, new_start, new_count
    return None


def find_recent_touch_commit(
    rev_range: str,
    file_path: str,
    allowed_commits: Set[str],
) -> str:
    result = run_git(
        ["log", "--format=%H", rev_range, "--", file_path],
        check=False,
    )
    if result.returncode != 0:
        return ""
    for line in result.stdout.splitlines():
        commit = line.strip()
        if commit and commit in allowed_commits:
            return commit
    return ""


def blame_counts(
    file_path: str,
    blame_commit: str,
    start: int,
    end: int,
    allowed_commits: Set[str],
) -> Dict[str, int]:
    if start > end:
        return {}

    result = run_git(
        ["blame", "-l", "-L", f"{start},{end}", blame_commit, "--", file_path],
        check=False,
    )
    if result.returncode != 0:
        return {}

    counts: Dict[str, int] = {}
    for line in result.stdout.splitlines():
        if not line:
            continue
        token = line.split()[0].lstrip("^")
        if not token or token == "0000000000":
            continue
        if token in allowed_commits:
            counts[token] = counts.get(token, 0) + 1
    return counts


def main() -> int:
    if len(sys.argv) < 3:
        usage()
        return 1

    args = parse_args(sys.argv[1:])
    rev_range = args.rev_range
    input_path = args.input_path
    output_path = args.output_path or input_path
    min_blame_hits = max(args.min_blame_hits, 1)
    min_lines = max(args.min_lines, 1)

    try:
        validate_range(rev_range)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    try:
        excluded_commits = {resolve_commit(commit) for commit in args.exclude}
        for rev_range in args.exclude_range:
            result = run_git(["rev-list", rev_range], check=False)
            if result.returncode != 0:
                raise ValueError(f"invalid exclude range: {rev_range}")
            excluded_commits.update(result.stdout.splitlines())
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    rev_list = run_git(["rev-list", rev_range]).stdout.splitlines()
    allowed_commits = set(rev_list) - excluded_commits

    if not allowed_commits:
        print(f"No commits found in range: {rev_range}", file=sys.stderr)
        return 1

    with open(input_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            print("Error: input CSV has no header", file=sys.stderr)
            return 1

        fieldnames: List[str] = list(reader.fieldnames)
        for required in ["target-commit", "target-file", "blame-hit-count", "blame-top-3"]:
            if required not in fieldnames:
                fieldnames.append(required)

        rows = list(reader)

    for row in rows:
        hunk_text = row.get("hunk", "") or row.get("patch", "") or ""
        if not hunk_text.strip():
            continue

        file_path = extract_file_path(row, hunk_text)
        if not file_path:
            continue

        header = parse_hunk_header(hunk_text)
        if header is None:
            target = find_recent_touch_commit(rev_range, file_path, allowed_commits)
            if target:
                row["target-commit"] = target
                row["target-file"] = file_path
                row["blame-hit-count"] = "0"
                row["blame-top-3"] = ""
            continue

        old_start, old_count, new_start, new_count = header
        commit_hash = row.get("commit-hash", "").strip()
        if not commit_hash:
            continue

        if new_count > 0:
            blame_commit = commit_hash
            start = new_start
            end = new_start + new_count - 1
        elif old_count > 0:
            blame_commit = f"{commit_hash}^"
            start = old_start
            end = old_start + old_count - 1
        else:
            continue

        hunk_size = max(old_count, new_count)
        if hunk_size < min_lines:
            continue

        row["blame-top-3"] = ""
        counts = blame_counts(file_path, blame_commit, start, end, allowed_commits)
        best_hash = ""
        best_count = 0
        if counts:
            sorted_counts = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
            best_hash, best_count = sorted_counts[0]
            row["blame-top-3"] = ",".join(
                [f"{commit}:{count}" for commit, count in sorted_counts[:3]]
            )

        if best_count < min_blame_hits:
            recent = find_recent_touch_commit(rev_range, file_path, allowed_commits)
            if recent:
                row["target-commit"] = recent
                row["target-file"] = file_path
                row["blame-hit-count"] = "0"
                row["blame-top-3"] = ""
            elif args.fallback == "parent":
                parent = resolve_commit_optional(f"{commit_hash}^")
                if parent and parent in allowed_commits:
                    row["target-commit"] = parent
                    row["target-file"] = file_path
                    row["blame-hit-count"] = "0"
                    row["blame-top-3"] = ""
            continue

        row["target-commit"] = best_hash
        row["target-file"] = file_path
        row["blame-hit-count"] = str(best_count)

    if output_path == input_path:
        with tempfile.NamedTemporaryFile("w", delete=False, newline="", encoding="utf-8") as tmp:
            writer = csv.DictWriter(tmp, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
            temp_path = tmp.name
        os.replace(temp_path, output_path)
    else:
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    print(f"Wrote: {output_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
