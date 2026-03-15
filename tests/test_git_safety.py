"""Tests for git safety: gitignore validation and pre-commit hook management."""

from __future__ import annotations

import stat
from pathlib import Path

from ai_sync.git_safety import (
    SENSITIVE_PATHS,
    _HOOK_MARKER,
    _HOOK_SCRIPT,
    check_gitignore,
    check_pre_commit_hook,
    install_pre_commit_hook,
    remove_pre_commit_hook,
    write_gitignore_entries,
)


# ── gitignore ──────────────────────────────────────────────


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
    gitignore.write_text(
        ".cursor/\n.codex/\n.gemini/\n.claude/\n.mcp.json\nCLAUDE.md\n.ai-sync/\n.ai-sync.local.yaml\n.env.ai-sync\n"
    )
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


# ── helpers ────────────────────────────────────────────────


def _make_git_repo(tmp_path: Path) -> Path:
    """Create a minimal .git directory and return the project root."""
    (tmp_path / ".git" / "hooks").mkdir(parents=True)
    return tmp_path


# ── check_pre_commit_hook ─────────────────────────────────


def test_check_hook_not_git_repo(tmp_path: Path) -> None:
    assert check_pre_commit_hook(tmp_path) == "not-git-repo"


def test_check_hook_missing(tmp_path: Path) -> None:
    _make_git_repo(tmp_path)
    assert check_pre_commit_hook(tmp_path) == "missing"


def test_check_hook_installed(tmp_path: Path) -> None:
    root = _make_git_repo(tmp_path)
    hook = root / ".git" / "hooks" / "pre-commit"
    hook.write_text(_HOOK_SCRIPT)
    assert check_pre_commit_hook(root) == "installed"


def test_check_hook_unrelated_hook_reports_missing(tmp_path: Path) -> None:
    root = _make_git_repo(tmp_path)
    hook = root / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho hello\n")
    assert check_pre_commit_hook(root) == "missing"


# ── install_pre_commit_hook ───────────────────────────────


def test_install_no_git_repo(tmp_path: Path) -> None:
    assert install_pre_commit_hook(tmp_path) is False


def test_install_fresh(tmp_path: Path) -> None:
    root = _make_git_repo(tmp_path)
    assert install_pre_commit_hook(root) is True
    hook = root / ".git" / "hooks" / "pre-commit"
    assert hook.exists()
    assert _HOOK_MARKER in hook.read_text()
    assert hook.stat().st_mode & stat.S_IXUSR


def test_install_wraps_existing_hook(tmp_path: Path) -> None:
    root = _make_git_repo(tmp_path)
    original_content = "#!/bin/sh\necho 'original hook'\n"
    hook = root / ".git" / "hooks" / "pre-commit"
    hook.write_text(original_content)
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR)

    assert install_pre_commit_hook(root) is True

    assert _HOOK_MARKER in hook.read_text()
    chain = root / ".git" / "hooks" / "pre-commit.ai-sync-chain"
    assert chain.exists()
    assert chain.read_text() == original_content


def test_install_idempotent(tmp_path: Path) -> None:
    root = _make_git_repo(tmp_path)
    install_pre_commit_hook(root)
    content1 = (root / ".git" / "hooks" / "pre-commit").read_text()
    install_pre_commit_hook(root)
    content2 = (root / ".git" / "hooks" / "pre-commit").read_text()
    assert content1 == content2
    assert not (root / ".git" / "hooks" / "pre-commit.ai-sync-chain").exists()


def test_install_does_not_overwrite_existing_chain(tmp_path: Path) -> None:
    root = _make_git_repo(tmp_path)
    hooks_dir = root / ".git" / "hooks"

    original_content = "#!/bin/sh\necho 'original'\n"
    (hooks_dir / "pre-commit").write_text(original_content)
    (hooks_dir / "pre-commit").chmod((hooks_dir / "pre-commit").stat().st_mode | stat.S_IXUSR)

    install_pre_commit_hook(root)
    chain = hooks_dir / "pre-commit.ai-sync-chain"
    assert chain.read_text() == original_content

    # Simulate someone replacing the hook again (not through ai-sync)
    # but chain backup already exists -- it should not be overwritten.
    (hooks_dir / "pre-commit").write_text("#!/bin/sh\necho 'second hook'\n")
    install_pre_commit_hook(root)
    assert chain.read_text() == original_content


def test_install_creates_hooks_dir_if_missing(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    assert install_pre_commit_hook(tmp_path) is True
    assert (tmp_path / ".git" / "hooks" / "pre-commit").exists()


# ── remove_pre_commit_hook ────────────────────────────────


def test_remove_no_git_repo(tmp_path: Path) -> None:
    assert remove_pre_commit_hook(tmp_path) is False


def test_remove_no_hook(tmp_path: Path) -> None:
    _make_git_repo(tmp_path)
    assert remove_pre_commit_hook(tmp_path) is False


def test_remove_unrelated_hook_left_alone(tmp_path: Path) -> None:
    root = _make_git_repo(tmp_path)
    hook = root / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho hello\n")
    assert remove_pre_commit_hook(root) is False
    assert hook.exists()


def test_remove_restores_chain(tmp_path: Path) -> None:
    root = _make_git_repo(tmp_path)
    original_content = "#!/bin/sh\necho 'original'\n"
    hook = root / ".git" / "hooks" / "pre-commit"
    chain = root / ".git" / "hooks" / "pre-commit.ai-sync-chain"

    hook.write_text(_HOOK_SCRIPT)
    chain.write_text(original_content)

    assert remove_pre_commit_hook(root) is True
    assert hook.read_text() == original_content
    assert not chain.exists()


def test_remove_deletes_when_no_chain(tmp_path: Path) -> None:
    root = _make_git_repo(tmp_path)
    hook = root / ".git" / "hooks" / "pre-commit"
    hook.write_text(_HOOK_SCRIPT)

    assert remove_pre_commit_hook(root) is True
    assert not hook.exists()


# ── git worktree support ──────────────────────────────────


def test_worktree_git_file_resolves_hooks_dir(tmp_path: Path) -> None:
    real_gitdir = tmp_path / "real-git" / "worktrees" / "wt"
    (real_gitdir / "hooks").mkdir(parents=True)

    worktree = tmp_path / "worktree-project"
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {real_gitdir}\n")

    assert install_pre_commit_hook(worktree) is True
    assert (real_gitdir / "hooks" / "pre-commit").exists()
    assert check_pre_commit_hook(worktree) == "installed"
    assert remove_pre_commit_hook(worktree) is True
    assert not (real_gitdir / "hooks" / "pre-commit").exists()
