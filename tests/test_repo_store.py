"""Tests for repo_store module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from ai_sync.repo_store import (
    RepoEntry,
    copy_repo_to_store,
    get_all_repo_roots,
    get_repo_root,
    load_repos,
    save_repos,
    validate_slug,
)


# ---------------------------------------------------------------------------
# validate_slug
# ---------------------------------------------------------------------------


def test_validate_slug_valid() -> None:
    assert validate_slug("my-config") is True
    assert validate_slug("team-config") is True
    assert validate_slug("abc") is True
    assert validate_slug("a1b2c3") is True
    assert validate_slug("a") is True


def test_validate_slug_invalid_slash() -> None:
    assert validate_slug("acme/config") is False


def test_validate_slug_invalid_uppercase() -> None:
    assert validate_slug("MyConfig") is False


def test_validate_slug_invalid_starts_with_dash() -> None:
    assert validate_slug("-bad") is False


def test_validate_slug_invalid_ends_with_dash() -> None:
    assert validate_slug("bad-") is False


def test_validate_slug_invalid_underscore() -> None:
    assert validate_slug("my_config") is False


# ---------------------------------------------------------------------------
# load_repos / save_repos
# ---------------------------------------------------------------------------


def test_load_repos_missing_file(tmp_path: Path) -> None:
    assert load_repos(tmp_path) == []


def test_save_and_load_repos_round_trip(tmp_path: Path) -> None:
    repos: list[RepoEntry] = [
        {"name": "team-config", "source": "https://example.com/team-config.git"},
        {"name": "personal", "source": "https://example.com/personal.git"},
    ]
    save_repos(tmp_path, repos)
    assert load_repos(tmp_path) == repos


def test_load_repos_skips_invalid_entries(tmp_path: Path) -> None:
    """Entries that are not dicts or lack required keys are silently skipped."""
    (tmp_path / "repos.yaml").write_text(
        yaml.safe_dump(
            {
                "repos": [
                    {"name": "valid", "source": "https://example.com/valid.git"},
                    "flat-string",
                    {"name": "no-source"},
                    {"source": "no-name"},
                    None,
                ]
            }
        )
    )
    result = load_repos(tmp_path)
    assert result == [{"name": "valid", "source": "https://example.com/valid.git"}]


def test_save_repos_is_atomic(tmp_path: Path) -> None:
    repos: list[RepoEntry] = [{"name": "first", "source": "https://example.com/first.git"}]
    save_repos(tmp_path, repos)
    assert not (tmp_path / "repos.yaml.tmp").exists()
    assert (tmp_path / "repos.yaml").exists()


def test_save_repos_cleans_tmp_on_failure(tmp_path: Path) -> None:
    # Patch yaml.safe_dump so the .tmp file is created first, then the write fails.
    import ai_sync.repo_store as rs_mod
    original_dump = yaml.safe_dump

    def failing_dump(data: object, stream: object, **kwargs: object) -> None:
        # Write partial content so the .tmp file exists, then raise.
        import io
        if isinstance(stream, io.IOBase):
            stream.write("partial")  # type: ignore[arg-type]
        raise OSError("disk full")

    with patch.object(rs_mod.yaml, "safe_dump", failing_dump):
        with pytest.raises(OSError):
            save_repos(tmp_path, [{"name": "repo", "source": "https://example.com/repo.git"}])
    assert not (tmp_path / "repos.yaml.tmp").exists()


# ---------------------------------------------------------------------------
# get_repo_root
# ---------------------------------------------------------------------------


def test_get_repo_root_remote_source(tmp_path: Path) -> None:
    entry: RepoEntry = {"name": "my-config", "source": "https://example.com/my-config.git"}
    assert get_repo_root(tmp_path, entry) == tmp_path / "repos" / "my-config"


def test_get_repo_root_absolute_source(tmp_path: Path) -> None:
    local = str(tmp_path / "my-local-config")
    entry: RepoEntry = {"name": "my-config", "source": local}
    assert get_repo_root(tmp_path, entry) == tmp_path / "my-local-config"


# ---------------------------------------------------------------------------
# get_all_repo_roots
# ---------------------------------------------------------------------------


def test_get_all_repo_roots_empty(tmp_path: Path) -> None:
    assert get_all_repo_roots(tmp_path) == []


def test_get_all_repo_roots_skips_missing_paths(tmp_path: Path) -> None:
    (tmp_path / "repos.yaml").write_text(
        yaml.safe_dump(
            {
                "repos": [
                    {"name": "exists", "source": "https://example.com/exists.git"},
                    {"name": "missing", "source": "https://example.com/missing.git"},
                ]
            }
        )
    )
    (tmp_path / "repos" / "exists").mkdir(parents=True)
    roots = get_all_repo_roots(tmp_path)
    assert len(roots) == 1
    assert roots[0].name == "exists"


def test_get_all_repo_roots_preserves_order(tmp_path: Path) -> None:
    (tmp_path / "repos.yaml").write_text(
        yaml.safe_dump(
            {
                "repos": [
                    {"name": "first", "source": "https://example.com/first.git"},
                    {"name": "second", "source": "https://example.com/second.git"},
                    {"name": "third", "source": "https://example.com/third.git"},
                ]
            }
        )
    )
    for name in ["first", "second", "third"]:
        (tmp_path / "repos" / name).mkdir(parents=True)
    roots = get_all_repo_roots(tmp_path)
    assert [r.name for r in roots] == ["first", "second", "third"]


# ---------------------------------------------------------------------------
# copy_repo_to_store
# ---------------------------------------------------------------------------


def test_copy_repo_to_store_basic(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "prompts").mkdir()
    (src / "prompts" / "agent.md").write_text("hi")

    dest = copy_repo_to_store(tmp_path, "my-repo", src)
    assert (dest / "prompts" / "agent.md").exists()
    assert dest == tmp_path / "repos" / "my-repo"


def test_copy_repo_to_store_replaces_existing(tmp_path: Path) -> None:
    src_v1 = tmp_path / "src-v1"
    src_v1.mkdir()
    (src_v1 / "old.md").write_text("old")
    copy_repo_to_store(tmp_path, "my-repo", src_v1)

    src_v2 = tmp_path / "src-v2"
    src_v2.mkdir()
    (src_v2 / "new.md").write_text("new")
    copy_repo_to_store(tmp_path, "my-repo", src_v2)

    dest = tmp_path / "repos" / "my-repo"
    assert (dest / "new.md").exists()
    assert not (dest / "old.md").exists()
    assert not (dest.parent / (dest.name + ".bak")).exists()


def test_copy_repo_to_store_rollback_on_failure(tmp_path: Path) -> None:
    src_v1 = tmp_path / "src-v1"
    src_v1.mkdir()
    (src_v1 / "original.md").write_text("original")
    copy_repo_to_store(tmp_path, "my-repo", src_v1)

    src_bad = tmp_path / "src-bad"
    src_bad.mkdir()

    with patch("shutil.copytree", side_effect=OSError("copy failed")):
        with pytest.raises(OSError, match="copy failed"):
            copy_repo_to_store(tmp_path, "my-repo", src_bad)

    dest = tmp_path / "repos" / "my-repo"
    assert (dest / "original.md").exists()
    assert not (dest.parent / (dest.name + ".bak")).exists()
