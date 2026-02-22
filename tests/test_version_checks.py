import json
from pathlib import Path

from ai_sync import version_checks


def test_check_client_versions_matches_major_minor(monkeypatch, tmp_path: Path) -> None:
    lock = tmp_path / "versions.json"
    lock.write_text(json.dumps({"codex": "1.2.3"}), encoding="utf-8")
    monkeypatch.setattr(version_checks, "detect_client_versions", lambda: {"codex": "1.2.99"})
    ok, _ = version_checks.check_client_versions(lock)
    assert ok


def test_check_client_versions_mismatch(monkeypatch, tmp_path: Path) -> None:
    lock = tmp_path / "versions.json"
    lock.write_text(json.dumps({"codex": "1.2.3"}), encoding="utf-8")
    monkeypatch.setattr(version_checks, "detect_client_versions", lambda: {"codex": "1.3.0"})
    ok, _ = version_checks.check_client_versions(lock)
    assert ok
