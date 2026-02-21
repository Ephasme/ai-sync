#!/usr/bin/env python3
import argparse
import base64
import csv
import datetime
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Union

SCRIPT_DIR = Path(__file__).resolve().parent
SPLIT_SCRIPT = SCRIPT_DIR / "split-commit-hunks.py"
UPDATE_SCRIPT = SCRIPT_DIR / "update-hunk-targets.py"
LOG_PATH: Optional[Path] = None


def run_git(
    args: Sequence[str],
    *,
    check: bool = True,
    cwd: Optional[Path] = None,
    env: Optional[dict] = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(cwd) if cwd else None,
        env=env,
    )


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Split a source commit into hunks, assign each hunk to the best target commit "
            "in a rev range via blame, then fixup and autosquash."
        )
    )
    parser.add_argument("rev_range", help="Commit range like base..HEAD")
    parser.add_argument("source_commit", help="Commit hash to absorb")
    parser.add_argument("--split-script", dest="split_script")
    parser.add_argument("--update-script", dest="update_script")
    parser.add_argument("--log-file", dest="log_file")
    parser.add_argument(
        "--allow-merges",
        action="store_true",
        help="Allow merge commits in the range (advanced)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute targets and summary only; do not rewrite history",
    )
    parser.add_argument(
        "--min-blame-hits",
        type=int,
        default=1,
        help="Minimum blame hits required to accept a target commit",
    )
    parser.add_argument(
        "--min-lines",
        type=int,
        default=1,
        help="Minimum hunk size (max of old/new counts) to consider",
    )
    parser.add_argument(
        "--fallback",
        choices=["skip", "parent"],
        default="skip",
        help="Fallback target selection when blame results are weak",
    )
    parser.add_argument(
        "--csv",
        dest="csv_path",
        help="Optional CSV path for hunk metadata (default: temp dir)",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep temporary directory with generated CSV and patches",
    )
    return parser.parse_args(argv)


def die(message: str) -> None:
    print(f"Error: {message}", file=sys.stderr)
    raise SystemExit(1)


def ensure_tooling() -> None:
    if sys.version_info < (3, 8):
        die("python 3.8+ is required")
    result = run_git(["--version"], check=False)
    if result.returncode != 0:
        die("git is required on PATH")
    pygit = subprocess.run(
        [sys.executable, "-c", "import pygit2"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if pygit.returncode != 0:
        die("pygit2 is required (install in the python used to run this script)")


def set_log_path(path: Path) -> None:
    global LOG_PATH
    LOG_PATH = path
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def log(message: str) -> None:
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{timestamp} {message}"
    print(line, file=sys.stderr)
    if LOG_PATH:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{line}\n")


def get_clean_status() -> None:
    status = run_git(["status", "--porcelain"]).stdout.strip()
    if status:
        die("working tree is not clean; commit or stash changes first")


def parse_range(rev_range: str) -> Tuple[str, str]:
    if "..." in rev_range:
        die("rev_range must use '..' (symmetric '...' ranges are unsupported)")
    if ".." in rev_range:
        left, right = rev_range.split("..", 1)
    else:
        die("rev_range must look like base..HEAD")

    left = left.strip()
    right = right.strip()
    if not left or not right:
        die("rev_range must include both base and end commits")
    return left, right


def resolve_commit(commitish: str) -> str:
    result = run_git(["rev-parse", commitish], check=False)
    if result.returncode != 0:
        die(f"invalid commit: {commitish}")
    return result.stdout.strip()


def resolve_commit_optional(commitish: str) -> Optional[str]:
    result = run_git(["rev-parse", "--verify", commitish], check=False)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def is_ancestor(ancestor: str, descendant: str) -> bool:
    result = run_git(["merge-base", "--is-ancestor", ancestor, descendant], check=False)
    return result.returncode == 0


def ensure_branch_order(base: str, range_end: str, source: str, head: str) -> None:
    if not is_ancestor(base, range_end):
        die("range base must be an ancestor of the range end")
    if not is_ancestor(range_end, source):
        die("source commit must be after the range end on the same branch")
    if not is_ancestor(source, head):
        die("HEAD must be at or after the source commit")


def ensure_no_merges(rev_range: str) -> None:
    merges = run_git(["rev-list", "--merges", rev_range]).stdout.splitlines()
    if merges:
        die("rev range contains merge commits; linear history required")


def ensure_source_not_edges(base: str, range_end: str, source: str) -> None:
    base_hash = resolve_commit(base)
    end_hash = resolve_commit(range_end)
    if source == base_hash:
        die("source commit cannot be the base of the range")
    if source == end_hash:
        die("source commit cannot be the range end (HEAD)")


def get_current_branch() -> Optional[str]:
    branch = run_git(["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    if branch == "HEAD":
        return None
    return branch


def create_backup_ref(orig_head: str) -> str:
    timestamp = run_git(
        [
            "show",
            "-s",
            "--format=%cd",
            "--date=format-local:%Y%m%d%H%M%S",
            "HEAD",
        ]
    ).stdout.strip()
    candidate = f"absorb-backup-{timestamp}"
    backup_name = candidate
    counter = 1
    while run_git(["show-ref", "--verify", f"refs/heads/{backup_name}"], check=False).returncode == 0:
        backup_name = f"{candidate}-{counter}"
        counter += 1
    run_git(["branch", backup_name, orig_head])
    return backup_name


def get_log_path() -> Path:
    result = run_git(["rev-parse", "--git-dir"], check=False)
    if result.returncode != 0:
        die("unable to determine .git directory")
    git_dir = result.stdout.strip()
    return (Path(git_dir) / "absorb-commit-into-range.log").resolve()


def write_sequence_editor(tmp_dir: Path) -> Path:
    editor_path = tmp_dir / "drop_commit.py"
    editor_path.write_text(
        """#!/usr/bin/env python3
import os
import sys

source = os.environ.get('ABSORB_DROP_SHA', '')
if not source:
    print('ABSORB_DROP_SHA not set', file=sys.stderr)
    raise SystemExit(1)

todo_path = sys.argv[1]
with open(todo_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

found = False
new_lines = []
for line in lines:
    if line.startswith('#') or not line.strip():
        new_lines.append(line)
        continue
    parts = line.split()
    if len(parts) < 2:
        new_lines.append(line)
        continue
    command, commit = parts[0], parts[1]
    if command in {'pick', 'reword', 'edit', 'squash', 'fixup'} and source.startswith(commit):
        new_lines.append(line.replace(command, 'drop', 1))
        found = True
    else:
        new_lines.append(line)

if not found:
    print('Commit not found in rebase todo', file=sys.stderr)
    raise SystemExit(1)

with open(todo_path, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
""",
        encoding="utf-8",
    )
    editor_path.chmod(0o755)
    return editor_path


def run_rebase_drop(base: str, source: str, tmp_dir: Path, *, rebase_merges: bool) -> None:
    editor_path = write_sequence_editor(tmp_dir)
    env = os.environ.copy()
    env["ABSORB_DROP_SHA"] = source
    env["GIT_SEQUENCE_EDITOR"] = str(editor_path)
    args = ["rebase", "-i", base]
    if rebase_merges:
        args.insert(2, "--rebase-merges")
    result = run_git(args, check=False, env=env)
    if result.returncode != 0:
        raise RuntimeError("rebase failed")


def is_rebase_in_progress() -> bool:
    result = run_git(["rev-parse", "--git-dir"], check=False)
    if result.returncode != 0:
        return False
    git_dir = Path(result.stdout.strip())
    return (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists()


def continue_rebase_allow_empty(env: dict) -> None:
    max_attempts = 50
    attempts = 0
    while attempts < max_attempts and is_rebase_in_progress():
        amend = run_git(["commit", "--allow-empty", "--amend", "--no-edit"], check=False, env=env)
        if amend.returncode != 0:
            message = amend.stderr.strip() or "allow-empty amend failed"
            raise RuntimeError(message)

        cont = run_git(["rebase", "--continue"], check=False, env=env)
        if cont.returncode == 0:
            if not is_rebase_in_progress():
                return
            attempts += 1
            continue

        if "amend the most recent commit" in cont.stderr:
            attempts += 1
            continue

        message = cont.stderr.strip() or "autosquash failed"
        raise RuntimeError(message)

    raise RuntimeError("autosquash failed (too many empty commits)")


def run_autosquash(base: str, *, rebase_merges: bool) -> None:
    args = ["rebase", "-i", "--autosquash", "--empty=keep", base]
    if rebase_merges:
        args.insert(2, "--rebase-merges")
    env = os.environ.copy()
    env["GIT_SEQUENCE_EDITOR"] = ":"
    env["GIT_EDITOR"] = ":"
    result = run_git(args, check=False, env=env)
    if result.returncode != 0:
        if "amend the most recent commit" in result.stderr:
            continue_rebase_allow_empty(env)
            return
        message = result.stderr.strip() or "autosquash failed"
        raise RuntimeError(message)


def drop_empty_commits(base: str, *, rebase_merges: bool) -> None:
    args = ["rebase", "-i", "--empty=drop", base]
    if rebase_merges:
        args.insert(2, "--rebase-merges")
    env = os.environ.copy()
    env["GIT_SEQUENCE_EDITOR"] = ":"
    env["GIT_EDITOR"] = ":"
    result = run_git(args, check=False, env=env)
    if result.returncode != 0:
        message = result.stderr.strip() or "drop empty commits failed"
        raise RuntimeError(message)


def load_hunks(csv_path: Path) -> List[Dict[str, str]]:
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


def summarize_targets(rows: Iterable[Dict[str, str]]) -> Tuple[int, int, Dict[str, int]]:
    total = 0
    missing = 0
    counts: Dict[str, int] = {}
    for row in rows:
        total += 1
        target = row.get("target-commit", "").strip()
        if not target:
            missing += 1
            continue
        counts[target] = counts.get(target, 0) + 1
    return total, missing, counts


def describe_commit(commit: str) -> str:
    result = run_git(["show", "-s", "--format=%h %s", commit], check=False)
    if result.returncode != 0:
        return commit
    return result.stdout.strip() or commit


def print_summary(rows: Iterable[Dict[str, str]], *, top_n: int = 10) -> None:
    total, missing, counts = summarize_targets(rows)
    log(f"Summary: {total} hunks, {missing} unassigned")
    for target, count in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:top_n]:
        log(f"  {describe_commit(target)}: {count}")


def check_patches_apply(rows: Iterable[Dict[str, str]], tmp_dir: Path) -> None:
    patch_path = tmp_dir / "hunk.patch"
    for row in rows:
        patch = row.get("patch", "") or row.get("hunk", "") or ""
        if not patch.strip():
            continue
        patch_bytes = decode_patch_data(patch)
        if isinstance(patch_bytes, bytes):
            patch_path.write_bytes(patch_bytes)
        else:
            patch_path.write_text(patch_bytes, encoding="utf-8")
        result = run_git(["apply", "--check", "--recount", str(patch_path)], check=False)
        if result.returncode != 0:
            message = result.stderr.strip() or "git apply --check failed"
            raise RuntimeError(message)


def apply_fixup_hunks(rows: Iterable[Dict[str, str]], tmp_dir: Path) -> None:
    patch_path = tmp_dir / "hunk.patch"
    for row in rows:
        target = row.get("target-commit", "").strip()
        patch = row.get("patch", "") or row.get("hunk", "") or ""
        if not target:
            raise RuntimeError("missing target commit for hunk")
        if not patch.strip():
            continue

        patch_bytes = decode_patch_data(patch)
        if isinstance(patch_bytes, bytes):
            patch_path.write_bytes(patch_bytes)
        else:
            patch_path.write_text(patch_bytes, encoding="utf-8")
        result = run_git(["apply", "--check", "--recount", str(patch_path)], check=False)
        if result.returncode != 0:
            message = result.stderr.strip() or "git apply --check failed"
            raise RuntimeError(message)

        result = run_git(["apply", "--index", "--recount", str(patch_path)], check=False)
        if result.returncode != 0:
            raise RuntimeError("git apply failed")

        staged = run_git(["diff", "--cached", "--name-only"]).stdout.strip()
        if not staged:
            raise RuntimeError("no staged changes after applying hunk")

        result = run_git(["commit", f"--fixup={target}"], check=False)
        if result.returncode != 0:
            raise RuntimeError("git commit --fixup failed")


def restore_state(orig_branch: Optional[str], orig_head: str) -> None:
    run_git(["rebase", "--abort"], check=False)
    if orig_branch:
        run_git(["update-ref", f"refs/heads/{orig_branch}", orig_head], check=False)
        run_git(["switch", orig_branch], check=False)
    else:
        run_git(["checkout", orig_head], check=False)
    run_git(["reset", "--hard", orig_head], check=False)


def decode_patch_data(patch: str) -> Union[str, bytes]:
    if patch.startswith("base64:"):
        encoded = patch[len("base64:") :]
        return base64.b64decode(encoded)
    return patch


def main() -> int:
    args = parse_args(sys.argv[1:])
    base, range_end = parse_range(args.rev_range)

    ensure_tooling()
    log_path = Path(args.log_file) if args.log_file else get_log_path()
    set_log_path(log_path)
    log("Starting absorb-commit-into-range")

    get_clean_status()
    source = resolve_commit(args.source_commit)
    head = resolve_commit("HEAD")
    ensure_branch_order(base, range_end, source, head)
    ensure_source_not_edges(base, range_end, source)
    if not args.allow_merges:
        ensure_no_merges(f"{base}..{head}")

    orig_head = resolve_commit("HEAD")
    orig_branch = get_current_branch()
    orig_origh = resolve_commit_optional("ORIG_HEAD")

    backup_branch = create_backup_ref(orig_head)
    temp_root = Path(tempfile.mkdtemp(prefix="absorb-commit-"))

    try:
        csv_path = Path(args.csv_path) if args.csv_path else temp_root / "hunks.csv"
        split_script = Path(args.split_script) if args.split_script else SPLIT_SCRIPT
        if not split_script.exists():
            raise RuntimeError(f"split script not found: {split_script}")
        update_script = Path(args.update_script) if args.update_script else UPDATE_SCRIPT
        if not update_script.exists():
            raise RuntimeError(f"update script not found: {update_script}")

        run_split = subprocess.run(
            [sys.executable, str(split_script), source, "--out", str(csv_path)],
            check=False,
            text=True,
        )
        if run_split.returncode != 0:
            raise RuntimeError("split-commit-hunks failed")

        run_update = subprocess.run(
            [
                sys.executable,
                str(update_script),
                args.rev_range,
                str(csv_path),
                "--exclude",
                source,
                "--min-blame-hits",
                str(max(args.min_blame_hits, 1)),
                "--min-lines",
                str(max(args.min_lines, 1)),
                "--fallback",
                args.fallback,
            ],
            check=False,
            text=True,
        )
        if run_update.returncode != 0:
            raise RuntimeError("update-hunk-targets failed")

        rows = load_hunks(csv_path)
        if not rows:
            raise RuntimeError("no hunks found in source commit")

        print_summary(rows)

        if any(row.get("target-commit", "").strip() == source for row in rows):
            raise RuntimeError("some hunks target the source commit")

        missing_targets = [row for row in rows if not row.get("target-commit", "").strip()]
        if missing_targets:
            raise RuntimeError("some hunks did not receive a target commit")

        if args.dry_run:
            log("Dry run: no history rewritten.")
            return 0

        current_origh = resolve_commit_optional("ORIG_HEAD")
        if current_origh != orig_origh:
            raise RuntimeError("ORIG_HEAD changed unexpectedly; aborting")

        run_rebase_drop(base, source, temp_root, rebase_merges=args.allow_merges)
        check_patches_apply(rows, temp_root)
        apply_fixup_hunks(rows, temp_root)
        run_autosquash(base, rebase_merges=args.allow_merges)
        drop_empty_commits(base, rebase_merges=args.allow_merges)

    except Exception as exc:
        log(f"Failure: {exc}")
        restore_state(orig_branch, orig_head)
        log(f"Restored original state. Backup branch: {backup_branch}")
        return 1
    finally:
        if not args.keep_temp:
            for path in temp_root.glob("*"):
                try:
                    path.unlink()
                except OSError:
                    pass
            try:
                temp_root.rmdir()
            except OSError:
                pass

    log(f"Success. Backup branch: {backup_branch}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
