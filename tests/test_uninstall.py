from __future__ import annotations

import json
from pathlib import Path

import tomli
import yaml

from ai_sync.track_write import WriteSpec, track_write_blocks
from ai_sync.uninstall import run_uninstall


# ---------------------------------------------------------------------------
# Text marker uninstall
# ---------------------------------------------------------------------------


def test_uninstall_removes_marker_block(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / ".gemini" / "GEMINI.md"
    spec = WriteSpec(
        file_path=target,
        format="text",
        target="ai-sync:mcp-instructions",
        value="## MCP\n\nUse work\n",
    )
    track_write_blocks([spec])
    assert target.exists()
    assert "BEGIN ai-sync:mcp-instructions" in target.read_text(encoding="utf-8")

    run_uninstall(apply=True)
    if target.exists():
        assert "BEGIN ai-sync:mcp-instructions" not in target.read_text(encoding="utf-8")


def test_uninstall_text_restores_baseline(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / "rules.mdc"
    target.parent.mkdir(parents=True, exist_ok=True)
    original_block = "<!-- BEGIN ai-sync:test -->\noriginal content\n<!-- END ai-sync:test -->"
    target.write_text(f"# Header\n\n{original_block}\n", encoding="utf-8")

    track_write_blocks([
        WriteSpec(file_path=target, format="text", target="ai-sync:test", value="replaced content"),
    ])
    assert "replaced content" in target.read_text(encoding="utf-8")

    run_uninstall(apply=True)
    restored = target.read_text(encoding="utf-8")
    assert "original content" in restored
    assert "replaced content" not in restored


# ---------------------------------------------------------------------------
# Structured JSON uninstall
# ---------------------------------------------------------------------------


def test_uninstall_structured_json_roundtrip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / "config.json"
    track_write_blocks([
        WriteSpec(file_path=target, format="json", target="/settings/theme", value="dark"),
        WriteSpec(file_path=target, format="json", target="/settings/lang", value="en"),
    ])
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["settings"]["theme"] == "dark"
    assert data["settings"]["lang"] == "en"

    run_uninstall(apply=True)
    data = json.loads(target.read_text(encoding="utf-8"))
    assert "theme" not in data.get("settings", {})
    assert "lang" not in data.get("settings", {})


def test_uninstall_structured_json_preserves_pre_existing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / "config.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('{"existing": true}', encoding="utf-8")

    track_write_blocks([
        WriteSpec(file_path=target, format="json", target="/added", value="new"),
    ])
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["existing"] is True
    assert data["added"] == "new"

    run_uninstall(apply=True)
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data.get("existing") is True
    assert "added" not in data


def test_uninstall_structured_json_restores_overwritten_value(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / "config.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('{"key": "original"}', encoding="utf-8")

    track_write_blocks([
        WriteSpec(file_path=target, format="json", target="/key", value="replaced"),
    ])
    assert json.loads(target.read_text(encoding="utf-8"))["key"] == "replaced"

    run_uninstall(apply=True)
    assert json.loads(target.read_text(encoding="utf-8"))["key"] == "original"


# ---------------------------------------------------------------------------
# Structured YAML uninstall
# ---------------------------------------------------------------------------


def test_uninstall_structured_yaml_roundtrip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / "config.yaml"
    track_write_blocks([
        WriteSpec(file_path=target, format="yaml", target="/servers/main/port", value=8080),
    ])
    data = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert data["servers"]["main"]["port"] == 8080

    run_uninstall(apply=True)
    data = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert "port" not in data.get("servers", {}).get("main", {})


# ---------------------------------------------------------------------------
# Structured TOML uninstall
# ---------------------------------------------------------------------------


def test_uninstall_structured_toml_roundtrip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / "config.toml"
    track_write_blocks([
        WriteSpec(file_path=target, format="toml", target="/tool/name", value="ai-sync"),
    ])
    data = tomli.loads(target.read_text(encoding="utf-8"))
    assert data["tool"]["name"] == "ai-sync"

    run_uninstall(apply=True)
    data = tomli.loads(target.read_text(encoding="utf-8"))
    assert "name" not in data.get("tool", {})


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


def test_uninstall_dry_run_does_not_modify(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / "config.json"
    track_write_blocks([
        WriteSpec(file_path=target, format="json", target="/key", value="val"),
    ])
    assert target.exists()
    content_before = target.read_text(encoding="utf-8")

    run_uninstall(apply=False)
    assert target.read_text(encoding="utf-8") == content_before


# ---------------------------------------------------------------------------
# Empty state
# ---------------------------------------------------------------------------


def test_uninstall_empty_state_returns_zero(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    result = run_uninstall(apply=True)
    assert result == 0


# ---------------------------------------------------------------------------
# Root-list JSON uninstall
# ---------------------------------------------------------------------------


def test_uninstall_structured_json_root_list(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / "list.json"
    track_write_blocks([
        WriteSpec(file_path=target, format="json", target="/", value=[]),
        WriteSpec(file_path=target, format="json", target="/0", value={"name": "alpha"}),
    ])
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data == [{"name": "alpha"}]

    run_uninstall(apply=True)
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data == {}
