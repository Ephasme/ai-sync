"""Service for fetching remote git sources."""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

from ai_sync.adapters.filesystem import FileSystem
from ai_sync.adapters.process_runner import ProcessRunner


class GitSourceFetcherService:
    """Fetch pinned remote git sources into project-managed cache."""

    def __init__(self, *, process_runner: ProcessRunner, filesystem: FileSystem) -> None:
        self._process_runner = process_runner
        self._filesystem = filesystem

    def clone_remote_source(self, source: str, version: str, dest: Path) -> None:
        self._filesystem.mkdir(dest.parent, parents=True, exist_ok=True)
        if self._is_checkout_at_version(dest, version):
            return

        tmp_dest = dest.parent / f".{dest.name}.tmp-{uuid.uuid4().hex}"
        if self._filesystem.exists(tmp_dest):
            self._filesystem.rmtree(tmp_dest, ignore_errors=True)

        try:
            self._process_runner.run(
                ["git", "clone", source, str(tmp_dest)],
                check=True,
                capture_output=True,
                text=True,
            )
            self._process_runner.run(
                ["git", "-C", str(tmp_dest), "checkout", version],
                check=True,
                capture_output=True,
                text=True,
            )
            if self._filesystem.exists(dest):
                self._filesystem.rmtree(dest, ignore_errors=True)
            self._filesystem.replace(tmp_dest, dest)
        except FileNotFoundError as exc:
            raise RuntimeError("git not found; install git to resolve remote ai-sync sources") from exc
        except subprocess.CalledProcessError as exc:
            msg = (exc.stderr or exc.stdout or "").strip()
            self._filesystem.rmtree(tmp_dest, ignore_errors=True)
            raise RuntimeError(
                f"Failed to resolve remote source {source!r} at {version!r}: {msg or 'git error'}"
            ) from exc

    def _is_checkout_at_version(self, dest: Path, version: str) -> bool:
        git_dir = dest / ".git"
        if not self._filesystem.is_dir(dest) or not self._filesystem.exists(git_dir):
            return False

        try:
            head = self._process_runner.run(
                ["git", "-C", str(dest), "rev-parse", "--verify", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            target = self._process_runner.run(
                ["git", "-C", str(dest), "rev-parse", "--verify", f"{version}^{{commit}}"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        except (FileNotFoundError, subprocess.CalledProcessError):
            return False

        return bool(head) and head == target
