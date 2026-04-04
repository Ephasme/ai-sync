from __future__ import annotations

import json
from pathlib import Path

import ai_sync.services.tool_version_service as tool_version_service_mod

from ai_sync.services.tool_version_service import ToolVersionService

from conftest import REAL_DETECT_CLIENT_VERSIONS


def test_check_client_versions_missing_file(tmp_path: Path) -> None:
    ok, msg = ToolVersionService().check_client_versions(tmp_path / "missing.json")
    assert not ok
    assert "Missing version lock file" in msg


def test_check_client_versions_invalid_json(tmp_path: Path) -> None:
    service = ToolVersionService()
    path = tmp_path / "versions.json"
    path.write_text("{", encoding="utf-8")
    ok, msg = service.check_client_versions(path)
    assert not ok
    assert "Failed to read" in msg


def test_check_client_versions_no_versions(tmp_path: Path, monkeypatch) -> None:
    service = ToolVersionService()
    path = tmp_path / "versions.json"
    path.write_text(json.dumps({"codex": "1.2.3"}), encoding="utf-8")
    monkeypatch.setattr(service, "detect_client_versions", lambda: {})
    ok, msg = service.check_client_versions(path)
    assert not ok
    assert "No client versions detected" in msg


def test_detect_client_versions_parses_output(monkeypatch) -> None:
    monkeypatch.setattr(ToolVersionService, "detect_client_versions", REAL_DETECT_CLIENT_VERSIONS)
    service = ToolVersionService()
    monkeypatch.setattr(tool_version_service_mod.shutil, "which", lambda *_args, **_kw: "/bin/codex")
    monkeypatch.setattr(service, "run_command_capture_output", lambda _cmd: "codex 1.2.3")
    versions = service.detect_client_versions()
    assert versions == {"codex": "1.2.3", "cursor": "1.2.3", "gemini": "1.2.3"}


def test_run_command_capture_output_handles_missing(monkeypatch) -> None:
    service = ToolVersionService()

    def _raise(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(tool_version_service_mod.subprocess, "run", _raise)
    assert service.run_command_capture_output(["nope"]) == ""
