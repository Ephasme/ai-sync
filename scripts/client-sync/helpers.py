"""Shared helpers for sync_ai_configs."""
import filecmp
import re
import shutil
import tarfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

_BACKUP_ROOT: Path | None = None


@contextmanager
def backup_context(root: Path | None):
    """Context manager that sets the backup root for the duration of the block.
    Use this instead of set_backup_root() for explicit scoping and testability.
    Pass None to disable backups."""
    global _BACKUP_ROOT
    prev = _BACKUP_ROOT
    _BACKUP_ROOT = root
    try:
        yield
    finally:
        _BACKUP_ROOT = prev


def _get_backup_root() -> Path | None:
    return _BACKUP_ROOT


def backup_path(path: Path) -> None:
    """Create a tar.gz backup of path (file or dir) before overwriting. No-op if path doesn't exist."""
    root = _get_backup_root()
    if not path.exists() or root is None:
        return
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        try:
            rel = path.relative_to(Path.home())
        except ValueError:
            rel = path
        name_safe = str(rel).replace("/", "_").replace("\\", "_")
        archive_name = f"{timestamp}_{name_safe}.tar.gz"
        backup_file = root / archive_name
        backup_file.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(backup_file, "w:gz") as tar:
            tar.add(path, arcname=path.name)
        print(f"  Backed up {path} -> {backup_file}")
    except OSError as e:
        print(f"  Warning: Could not backup {path}: {e}")


def parse_duration_seconds(value: str | int | float) -> int:
    """Parse duration string (e.g. '30s', '1m20s', '2h') or number into seconds.
    Uses pytimeparse. Returns integer seconds. Raises ValueError for invalid input."""
    from pytimeparse import parse as timeparse

    if isinstance(value, (int, float)):
        return int(value)
    s = str(value).strip()
    result = timeparse(s)
    if result is None:
        raise ValueError(f"Invalid duration: {value!r}")
    return int(result)


def to_kebab_case(name: str) -> str:
    """Converts snake_case or mixed strings to kebab-case."""
    s = re.sub(r"[_ ]+", "-", name)
    return s.lower()


def ensure_dir(path: Path) -> None:
    if not path.exists():
        path.mkdir(parents=True)


def write_content_if_different(path: Path, content: str, *, backup: bool = True) -> bool:
    """Writes content to path only if it would change the file.
    Backs up before overwriting when backup=True. Returns True if wrote.
    """
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                if f.read() == content:
                    return False
            if backup:
                backup_path(path)
        except (OSError, UnicodeDecodeError):
            return False
    ensure_dir(path.parent)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return True


def deep_merge(base: dict, overlay: dict) -> dict:
    """Deep-merge overlay into base. Returns new dict.
    Dict values are recursively merged; other values (including lists) are replaced by overlay, not deep-copied."""
    result: dict = {}
    for k, v in base.items():
        result[k] = dict(v) if isinstance(v, dict) else v
    for k, v in overlay.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def copy_file_if_different(src: Path, dst: Path, *, backup: bool = True) -> bool:
    """Copies src to dst only if dst doesn't exist or has different content.
    Backs up before overwriting when backup=True. Returns True if copied.
    """
    if not src.exists():
        return False
    if dst.exists() and filecmp.cmp(src, dst, shallow=False):
        return False
    if dst.exists() and backup:
        backup_path(dst)
    ensure_dir(dst.parent)
    shutil.copy2(src, dst)
    return True


def sync_tree_if_different(
    src: Path, dst: Path, skip_patterns: set[str], *, backup: bool = True
) -> bool:
    """
    Copies src tree to dst; overwrites existing files that differ.
    Skips paths containing any component in skip_patterns.
    Does not remove files in dst that are not in src (untracked left alone).
    Returns True if any change was made.
    """
    changed = False

    def should_skip(relative_path: Path) -> bool:
        return any(part in skip_patterns for part in relative_path.parts)

    for item in src.rglob("*"):
        rel = item.relative_to(src)
        if item.is_file() and not should_skip(rel):
            target = dst / rel
            if not target.exists() or not filecmp.cmp(item, target, shallow=False):
                if target.exists() and backup:
                    backup_path(target)
                ensure_dir(target.parent)
                shutil.copy2(item, target)
                changed = True

    return changed


def extract_description(content: str) -> str:
    """Extracts a short description from the markdown content."""
    match = re.search(r"## Task\s+(.*)", content, re.IGNORECASE | re.DOTALL)
    if match:
        desc = match.group(1).strip().split("\n")[0]
        return desc[:150] + "..." if len(desc) > 150 else desc
    for line in content.splitlines():
        if line.strip() and not line.startswith("#"):
            return line.strip()[:100]
    return "AI Agent"
