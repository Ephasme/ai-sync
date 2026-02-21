#!/usr/bin/env python3
import argparse
import base64
import csv
import os
import sys
from pathlib import Path
from typing import Iterable, List, Optional

try:
    import pygit2
except ImportError:  # pragma: no cover - runtime environment dependent
    pygit2 = None


def usage() -> None:
    prog = os.path.basename(sys.argv[0])
    print(f"Usage: {prog} <commit-ish> [output-file]", file=sys.stderr)
    print(f"       {prog} <commit-ish> --out <output-path>", file=sys.stderr)
    print(f"Example: {prog} HEAD~1 hunks.csv", file=sys.stderr)
    print(f"Example: {prog} HEAD~1 --out ./out", file=sys.stderr)
    print(f"Example: {prog} HEAD~1 --cwd /path/to/repo --out ./out", file=sys.stderr)
    print("Env: COMMIT_HUNKS_OUT can specify output path", file=sys.stderr)


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("commit")
    parser.add_argument("output_file", nargs="?")
    parser.add_argument("--out", dest="out")
    parser.add_argument("--cwd")
    parser.add_argument("-h", "--help", action="help", default=argparse.SUPPRESS)
    return parser.parse_args(argv)


def resolve_output_path(
    target: Optional[str],
    default_name: str,
) -> Path:
    if target is None or target == "":
        return Path(default_name)
    path = Path(target)
    if path.suffix:
        return path
    return path / default_name


def main() -> int:
    if pygit2 is None:
        print("pygit2 is required. Install with: pip install pygit2", file=sys.stderr)
        return 1

    if len(sys.argv) < 2:
        usage()
        return 1

    args = parse_args(sys.argv[1:])
    commit = args.commit

    repo_root = args.cwd or "."
    repo_dir = pygit2.discover_repository(repo_root)
    if repo_dir is None:
        print(f"Unable to find git repository at: {repo_root}", file=sys.stderr)
        return 1

    repo = pygit2.Repository(repo_dir)
    commit_obj = repo.revparse_single(commit)
    if not isinstance(commit_obj, pygit2.Commit):
        try:
            commit_obj = commit_obj.peel(pygit2.Commit)
        except Exception as exc:
            print(f"Unable to resolve commit: {commit} ({exc})", file=sys.stderr)
            return 1
    commit_hash = str(commit_obj.id)
    message = commit_obj.message or ""
    subject = message.splitlines()[0] if message else ""
    default_name = f"commit-hunks-{commit_hash}.csv"
    out_arg = args.out or args.output_file
    out_env = os.getenv("COMMIT_HUNKS_OUT")
    out_target = out_arg if out_arg else out_env
    out_file = resolve_output_path(out_target, default_name)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    if commit_obj.parents:
        diff = repo.diff(commit_obj.parents[0], commit_obj)
    else:
        diff = commit_obj.tree.diff_to_tree(swap=True)

    def ensure_nl(s: str) -> str:
        return s if s.endswith("\n") else f"{s}\n"

    def coerce_text(value: object) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)

    def encode_patch_data(data: object) -> str:
        if isinstance(data, bytes):
            try:
                return data.decode("utf-8")
            except UnicodeDecodeError:
                encoded = base64.b64encode(data).decode("ascii")
                return f"base64:{encoded}"
        return str(data)

    def is_strict_utf8(data: bytes) -> bool:
        try:
            data.decode("utf-8")
            return True
        except UnicodeDecodeError:
            return False

    def _status_from_enum(delta: "pygit2.DiffDelta") -> str:
        status = getattr(delta, "status", None)
        if status is None:
            return ""
        try:
            delta_status = pygit2.enums.DeltaStatus
        except Exception:
            return ""

        if status == delta_status.ADDED:
            return "A"
        if status == delta_status.DELETED:
            return "D"
        if status == delta_status.MODIFIED:
            return "M"
        if status == delta_status.RENAMED:
            return "R"
        if status == delta_status.COPIED:
            return "C"
        if status == delta_status.TYPECHANGE:
            return "T"
        if status == delta_status.UNREADABLE:
            return "U"
        if status == delta_status.CONFLICTED:
            return "X"
        if status == delta_status.UNMODIFIED:
            return " "
        return ""

    def status_char(delta: "pygit2.DiffDelta") -> str:
        value = getattr(delta, "status_char", "")
        if callable(value):
            value = value()
        if value is None:
            value = ""
        value = str(value)
        if value:
            return value
        return _status_from_enum(delta)

    def format_mode(value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, int):
            return f"{value:06o}"
        return str(value)

    def patch_header_lines(delta: "pygit2.DiffDelta") -> List[str]:
        old_path = coerce_text(delta.old_file.path or "")
        new_path = coerce_text(delta.new_file.path or "")

        diff_old = old_path or new_path
        diff_new = new_path or old_path

        status = status_char(delta)
        old_mode = getattr(delta.old_file, "mode", None)
        new_mode = getattr(delta.new_file, "mode", None)
        old_id = getattr(delta.old_file, "id", None)
        new_id = getattr(delta.new_file, "id", None)

        header: List[str] = [f"diff --git a/{diff_old} b/{diff_new}\n"]

        if status == "A":
            mode_text = format_mode(new_mode)
            if mode_text:
                header.append(f"new file mode {mode_text}\n")
        elif status == "D":
            mode_text = format_mode(old_mode)
            if mode_text:
                header.append(f"deleted file mode {mode_text}\n")
        elif old_mode is not None and new_mode is not None and old_mode != new_mode:
            old_mode_text = format_mode(old_mode)
            new_mode_text = format_mode(new_mode)
            if old_mode_text:
                header.append(f"old mode {old_mode_text}\n")
            if new_mode_text:
                header.append(f"new mode {new_mode_text}\n")

        if status in {"R", "C"} and old_path and new_path and old_path != new_path:
            if status == "R":
                header.append(f"rename from {old_path}\n")
                header.append(f"rename to {new_path}\n")
            else:
                header.append(f"copy from {old_path}\n")
                header.append(f"copy to {new_path}\n")

        if old_id is not None and new_id is not None:
            old_id_text = str(old_id)
            new_id_text = str(new_id)
            if status == "D":
                mode_text = format_mode(old_mode)
            elif status == "A":
                mode_text = format_mode(new_mode)
            elif old_mode is not None and new_mode is not None and old_mode == new_mode:
                mode_text = format_mode(new_mode)
            else:
                mode_text = format_mode(new_mode) or format_mode(old_mode)
            if mode_text:
                header.append(f"index {old_id_text}..{new_id_text} {mode_text}\n")
            else:
                header.append(f"index {old_id_text}..{new_id_text}\n")

        if status == "A":
            old_label = "/dev/null"
            new_label = f"b/{new_path}"
        elif status == "D":
            old_label = f"a/{old_path}"
            new_label = "/dev/null"
        else:
            old_label = f"a/{old_path}"
            new_label = f"b/{new_path}"

        header.append(f"--- {old_label}\n")
        header.append(f"+++ {new_label}\n")
        return header

    def hunk_lines(hunk: "pygit2.DiffHunk") -> Iterable[str]:
        yield ensure_nl(coerce_text(hunk.header))
        for line in hunk.lines:
            content = ensure_nl(coerce_text(line.content))
            origin = getattr(line, "origin", "")
            if isinstance(origin, int):
                origin = chr(origin)
            origin = str(origin) if origin is not None else ""
            if origin in {"+", "-", " ", "\\"}:
                yield f"{origin}{content}"
            else:
                yield content

    with open(out_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "commit-name",
                "commit-hash",
                "target-commit",
                "patch",
                "hunk",
                "blame-hit-count",
                "target-file",
                "file-old",
                "file-new",
                "status",
                "old-mode",
                "new-mode",
                "old-id",
                "new-id",
            ]
        )

        for patch in diff:
            delta = patch.delta
            old_path = coerce_text(delta.old_file.path or "")
            new_path = coerce_text(delta.new_file.path or "")
            file_path = new_path or old_path
            header_lines = patch_header_lines(delta)
            status = status_char(delta)
            old_mode = format_mode(getattr(delta.old_file, "mode", None))
            new_mode = format_mode(getattr(delta.new_file, "mode", None))
            old_id = getattr(delta.old_file, "id", None)
            new_id = getattr(delta.new_file, "id", None)
            old_id_text = str(old_id) if old_id is not None else ""
            new_id_text = str(new_id) if new_id is not None else ""

            patch_data = getattr(patch, "data", None)
            if isinstance(patch_data, bytes) and not is_strict_utf8(patch_data):
                patch_text = encode_patch_data(patch_data)
                name = f"{subject} | {file_path} | (binary)"
                writer.writerow(
                    [
                        name,
                        commit_hash,
                        "",
                        patch_text,
                        "",
                        "",
                        "",
                        old_path,
                        new_path,
                        status,
                        old_mode,
                        new_mode,
                        old_id_text,
                        new_id_text,
                    ]
                )
                continue

            if not patch.hunks:
                patch_data = getattr(patch, "data", None)
                if not patch_data:
                    continue
                patch_text = encode_patch_data(patch_data)
                name = f"{subject} | {file_path} | (no hunks)"
                writer.writerow(
                    [
                        name,
                        commit_hash,
                        "",
                        patch_text,
                        "",
                        "",
                        "",
                        old_path,
                        new_path,
                        status,
                        old_mode,
                        new_mode,
                        old_id_text,
                        new_id_text,
                    ]
                )
                continue

            for hunk in patch.hunks:
                hunk_header = coerce_text(hunk.header).rstrip("\n")
                hunk_text = "".join(hunk_lines(hunk))
                patch_text = "".join(header_lines) + hunk_text
                name = f"{subject} | {file_path} | {hunk_header}"
                writer.writerow(
                    [
                        name,
                        commit_hash,
                        "",
                        patch_text,
                        hunk_text,
                        "",
                        "",
                        old_path,
                        new_path,
                        status,
                        old_mode,
                        new_mode,
                        old_id_text,
                        new_id_text,
                    ]
                )

    print(f"Wrote: {out_file}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
