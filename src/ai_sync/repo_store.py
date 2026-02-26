"""Repository store management for ai-sync."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import TypedDict

import yaml

REPOS_FILE = "repos.yaml"

SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
SLUG_ERROR_MSG = (
    "Name must match [a-z0-9]([a-z0-9-]*[a-z0-9])? (lowercase, no leading/trailing hyphens)"
)


class RepoEntry(TypedDict):
    name: str
    source: str


def validate_slug(name: str) -> bool:
    return bool(SLUG_RE.fullmatch(name))


def _dest_for_name(config_root: Path, name: str) -> Path:
    return config_root / "repos" / name


def load_repos(config_root: Path) -> list[RepoEntry]:
    """Load the ordered repo list from repos.yaml. Returns [] if the file is missing.

    Entries that are not dicts with both ``name`` and ``source`` string keys
    are silently skipped.
    """
    repos_path = config_root / REPOS_FILE
    if not repos_path.exists():
        return []
    try:
        with open(repos_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (yaml.YAMLError, OSError):
        return []
    if not isinstance(data, dict):
        return []
    raw = data.get("repos") or []
    result: list[RepoEntry] = []
    for item in raw:
        if (
            isinstance(item, dict)
            and isinstance(item.get("name"), str)
            and isinstance(item.get("source"), str)
        ):
            result.append(RepoEntry(name=item["name"], source=item["source"]))
    return result


def save_repos(config_root: Path, repos: list[RepoEntry]) -> None:
    """Write repos.yaml atomically to prevent corruption on crash."""
    repos_path = config_root / REPOS_FILE
    tmp_path = config_root / (REPOS_FILE + ".tmp")
    data: dict = {"repos": [dict(e) for e in repos]}
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, default_flow_style=False)
        tmp_path.replace(repos_path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise


def get_repo_root(config_root: Path, entry: RepoEntry) -> Path:
    """Return the stored path for a repo entry.

    If ``entry["source"]`` is an absolute path it is returned directly; this is
    how local-path imports are stored — they are referenced in-place rather than
    copied.
    """
    source = Path(entry["source"])
    if source.is_absolute():
        return source
    return _dest_for_name(config_root, entry["name"])


def get_all_repo_roots(config_root: Path) -> list[Path]:
    """Return all repo root paths in priority order (last = highest priority).

    Entries whose directory does not exist on disk are silently skipped.
    """
    roots = []
    for entry in load_repos(config_root):
        path = get_repo_root(config_root, entry)
        if path.exists():
            roots.append(path)
    return roots


def copy_repo_to_store(config_root: Path, name: str, src: Path) -> Path:
    """Copy repo src into the store with atomic rollback on failure.

    If the destination already exists it is backed up first. On success the
    backup is removed; on any failure the backup is restored and the exception
    is re-raised.
    """
    dest = _dest_for_name(config_root, name)
    dest.parent.mkdir(parents=True, exist_ok=True)

    bak = dest.parent / (dest.name + ".bak")
    if bak.exists():
        shutil.rmtree(bak)

    if dest.exists():
        dest.rename(bak)

    try:
        shutil.copytree(src, dest)
    except Exception:
        if dest.exists():
            shutil.rmtree(dest)
        if bak.exists():
            bak.rename(dest)
        raise
    else:
        if bak.exists():
            shutil.rmtree(bak)

    return dest
