"""Project-driven source resolution for ai-sync."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .project import ProjectManifest, SourceConfig

SKIP_FINGERPRINT_PARTS = {".git", ".venv", "node_modules", "__pycache__", ".DS_Store"}


@dataclass(frozen=True)
class ResolvedSource:
    alias: str
    source: str
    version: str | None
    root: Path
    kind: str
    fingerprint: str
    portability_warning: str | None = None


def is_local_source(project_root: Path, source: str) -> bool:
    if source.startswith(("./", "../", "/", "~")):
        return True
    candidate = (project_root / source).expanduser()
    return candidate.exists()


def resolve_sources(project_root: Path, manifest: ProjectManifest) -> dict[str, ResolvedSource]:
    sources_dir = project_root / ".ai-sync" / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)

    resolved: dict[str, ResolvedSource] = {}
    for alias, cfg in manifest.sources.items():
        resolved[alias] = _resolve_source(project_root, sources_dir, alias, cfg)
    return resolved


def _resolve_source(project_root: Path, sources_dir: Path, alias: str, cfg: SourceConfig) -> ResolvedSource:
    if is_local_source(project_root, cfg.source):
        root = _resolve_local_source(project_root, cfg.source)
        if not root.is_dir():
            raise RuntimeError(f"Local source {cfg.source!r} for alias {alias!r} does not exist or is not a directory.")
        return ResolvedSource(
            alias=alias,
            source=cfg.source,
            version=cfg.version,
            root=root,
            kind="local",
            fingerprint=_fingerprint_path(root),
            portability_warning="Local path source; portability depends on the current machine state.",
        )

    if not cfg.version:
        raise RuntimeError(f"Remote source {cfg.source!r} for alias {alias!r} must define a pinned version.")

    root = sources_dir / alias
    _clone_remote_source(cfg.source, cfg.version, root)
    return ResolvedSource(
        alias=alias,
        source=cfg.source,
        version=cfg.version,
        root=root,
        kind="remote",
        fingerprint=_git_head_or_fingerprint(root),
    )


def _resolve_local_source(project_root: Path, source: str) -> Path:
    return (Path(source).expanduser() if source.startswith("~") else (project_root / source)).resolve()


def _clone_remote_source(source: str, version: str, dest: Path) -> None:
    tmp_dest = dest.parent / f".{dest.name}.tmp"
    if tmp_dest.exists():
        shutil.rmtree(tmp_dest, ignore_errors=True)
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)

    try:
        subprocess.run(["git", "clone", source, str(tmp_dest)], check=True, capture_output=True, text=True)
        subprocess.run(["git", "-C", str(tmp_dest), "checkout", version], check=True, capture_output=True, text=True)
        tmp_dest.replace(dest)
    except FileNotFoundError as exc:
        raise RuntimeError("git not found; install git to resolve remote ai-sync sources") from exc
    except subprocess.CalledProcessError as exc:
        msg = (exc.stderr or exc.stdout or "").strip()
        shutil.rmtree(tmp_dest, ignore_errors=True)
        raise RuntimeError(f"Failed to resolve remote source {source!r} at {version!r}: {msg or 'git error'}") from exc


def _git_head_or_fingerprint(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        head = result.stdout.strip()
        if head:
            return head
    except (OSError, subprocess.CalledProcessError):
        pass
    return _fingerprint_path(root)


def _fingerprint_path(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if any(part in SKIP_FINGERPRINT_PARTS for part in rel.parts):
            continue
        digest.update(rel.as_posix().encode("utf-8"))
        if path.is_file():
            try:
                digest.update(path.read_bytes())
            except OSError as exc:
                raise RuntimeError(f"Failed to read {path}: {exc}") from exc
    return digest.hexdigest()
