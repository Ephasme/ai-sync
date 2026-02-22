from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_sync import version_checks


def test_check_client_versions_missing_file(tmp_path: Path) -> None:
    ok, msg = version_checks.check_client_versions(tmp_path / "missing.json")
    assert not ok
    assert "Missing version lock file" in msg


def test_check_client_versions_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "versions.json"
    path.write_text("{", encoding="utf-8")
    ok, msg = version_checks.check_client_versions(path)
    assert not ok
    assert "Failed to read" in msg


def test_check_client_versions_no_versions(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "versions.json"
    path.write_text(json.dumps({"codex": "1.2.3"}), encoding="utf-8")
    monkeypatch.setattr(version_checks, "detect_client_versions", lambda: {})
    ok, msg = version_checks.check_client_versions(path)
    assert not ok
    assert "No client versions detected" in msg


def test_detect_client_versions_parses_output(monkeypatch) -> None:
    monkeypatch.setattr(version_checks.shutil, "which", lambda *_args, **_kw: "/bin/codex")
    monkeypatch.setattr(version_checks, "run_command_capture_output", lambda _cmd: "codex 1.2.3")
    versions = version_checks.detect_client_versions()
    assert versions == {"codex": "1.2.3", "cursor": "1.2.3", "gemini": "1.2.3"}


def test_run_command_capture_output_handles_missing(monkeypatch) -> None:
    def _raise(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(version_checks.subprocess, "run", _raise)
    assert version_checks.run_command_capture_output(["nope"]) == ""
