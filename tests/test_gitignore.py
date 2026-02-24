"""Tests for gitignore validation gate."""

from pathlib import Path

from ai_sync.gitignore import check_gitignore, write_gitignore_entries, SENSITIVE_PATHS


def test_no_gitignore_returns_all(tmp_path: Path) -> None:
    uncovered = check_gitignore(tmp_path)
    assert uncovered == SENSITIVE_PATHS


def test_full_coverage(tmp_path: Path) -> None:
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("\n".join(SENSITIVE_PATHS) + "\n")
    uncovered = check_gitignore(tmp_path)
    assert uncovered == []


def test_parent_dir_covers_child(tmp_path: Path) -> None:
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text(".cursor/\n.codex/\n.gemini/\n.ai-sync.local.yaml\n.ai-sync/\n")
    uncovered = check_gitignore(tmp_path)
    assert uncovered == []


def test_partial_coverage(tmp_path: Path) -> None:
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text(".cursor/*\n")
    uncovered = check_gitignore(tmp_path)
    assert ".cursor/*" not in uncovered
    assert ".codex/*" in uncovered


def test_write_gitignore_entries_creates_file(tmp_path: Path) -> None:
    write_gitignore_entries(tmp_path, SENSITIVE_PATHS)
    gitignore = tmp_path / ".gitignore"
    assert gitignore.exists()
    content = gitignore.read_text()
    for path in SENSITIVE_PATHS:
        assert path in content
    assert "# ai-sync managed entries" in content


def test_write_gitignore_entries_appends(tmp_path: Path) -> None:
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("node_modules/\n")
    write_gitignore_entries(tmp_path, SENSITIVE_PATHS)
    content = gitignore.read_text()
    assert content.startswith("node_modules/")
    assert "# ai-sync managed entries" in content


def test_write_gitignore_entries_idempotent(tmp_path: Path) -> None:
    write_gitignore_entries(tmp_path, SENSITIVE_PATHS)
    content1 = (tmp_path / ".gitignore").read_text()
    write_gitignore_entries(tmp_path, SENSITIVE_PATHS)
    content2 = (tmp_path / ".gitignore").read_text()
    assert content1 == content2
