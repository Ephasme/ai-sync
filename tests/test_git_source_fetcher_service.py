from __future__ import annotations

import subprocess
from pathlib import Path

from ai_sync.adapters.filesystem import FileSystem
from ai_sync.adapters.process_runner import ProcessRunner
from ai_sync.services.git_source_fetcher_service import GitSourceFetcherService


class RecordingProcessRunner(ProcessRunner):
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def run(self, args, **kwargs):  # type: ignore[override]
        self.calls.append(list(args))
        return super().run(args, **kwargs)


def _git(args: list[str], cwd: Path | None = None) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


def _init_origin_repo(tmp_path: Path) -> tuple[Path, str]:
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(["git", "init", "-b", "main"], cwd=origin)
    _git(["git", "config", "user.name", "Test User"], cwd=origin)
    _git(["git", "config", "user.email", "test@example.com"], cwd=origin)
    (origin / "README.md").write_text("hello\n", encoding="utf-8")
    _git(["git", "add", "README.md"], cwd=origin)
    _git(["git", "commit", "-m", "init"], cwd=origin)
    _git(["git", "update-ref", "refs/tags/v1.0.0", "HEAD"], cwd=origin)
    head = (
        subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=origin,
            check=True,
            capture_output=True,
            text=True,
        )
        .stdout.strip()
    )
    return origin, head


def test_clone_remote_source_clones_and_checks_out_requested_version(tmp_path: Path) -> None:
    origin, head = _init_origin_repo(tmp_path)
    runner = RecordingProcessRunner()
    service = GitSourceFetcherService(process_runner=runner, filesystem=FileSystem())
    dest = tmp_path / "cache" / "source"

    service.clone_remote_source(str(origin), "v1.0.0", dest)

    cloned_head = (
        subprocess.run(
            ["git", "-C", str(dest), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        .stdout.strip()
    )
    assert cloned_head == head
    assert (dest / "README.md").exists()
    assert any(call[:2] == ["git", "clone"] for call in runner.calls)


def test_clone_remote_source_reuses_existing_checkout_for_same_version(tmp_path: Path) -> None:
    origin, _head = _init_origin_repo(tmp_path)
    runner = RecordingProcessRunner()
    service = GitSourceFetcherService(process_runner=runner, filesystem=FileSystem())
    dest = tmp_path / "cache" / "source"

    service.clone_remote_source(str(origin), "v1.0.0", dest)
    clone_calls_after_first_run = [
        call for call in runner.calls if call[:2] == ["git", "clone"]
    ]

    service.clone_remote_source(str(origin), "v1.0.0", dest)
    clone_calls_after_second_run = [
        call for call in runner.calls if call[:2] == ["git", "clone"]
    ]

    assert len(clone_calls_after_first_run) == 1
    assert len(clone_calls_after_second_run) == 1
