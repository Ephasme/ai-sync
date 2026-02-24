"""Gitignore validation gate for secret-bearing files."""

from __future__ import annotations

from pathlib import Path

import pathspec

SENSITIVE_PATHS = [
    ".cursor/*",
    ".codex/*",
    ".gemini/*",
    ".ai-sync.local.yaml",
    ".ai-sync/state/",
]

_GITIGNORE_SECTION_HEADER = "# ai-sync managed entries"


def check_gitignore(project_root: Path) -> list[str]:
    gitignore_path = project_root / ".gitignore"
    if not gitignore_path.exists():
        return list(SENSITIVE_PATHS)

    content = gitignore_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    spec = pathspec.PathSpec.from_lines("gitignore", lines)

    uncovered: list[str] = []
    for sensitive_path in SENSITIVE_PATHS:
        test_path = sensitive_path.rstrip("/")
        if sensitive_path.endswith("/"):
            test_path_with_child = test_path + "/dummy"
            if not spec.match_file(test_path_with_child) and not spec.match_file(test_path):
                uncovered.append(sensitive_path)
        else:
            if not spec.match_file(test_path):
                uncovered.append(sensitive_path)
    return uncovered


def write_gitignore_entries(project_root: Path, entries: list[str]) -> None:
    if not entries:
        return
    gitignore_path = project_root / ".gitignore"
    existing = ""
    if gitignore_path.exists():
        existing = gitignore_path.read_text(encoding="utf-8")

    if _GITIGNORE_SECTION_HEADER in existing:
        return

    section = f"\n{_GITIGNORE_SECTION_HEADER}\n" + "\n".join(entries) + "\n"
    if existing and not existing.endswith("\n"):
        section = "\n" + section

    with open(gitignore_path, "a", encoding="utf-8") as f:
        f.write(section)
