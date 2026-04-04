from __future__ import annotations

import json
import os
from pathlib import Path

import tomli
import yaml

from ai_sync.adapters.state_store import StateStore
from ai_sync.data_classes.write_spec import WriteSpec
from ai_sync.di import create_container


def _track_write(specs: list[WriteSpec], store: StateStore) -> None:
    container = create_container()
    container.managed_output_service().track_write_blocks(specs, store)


def _run_uninstall(project_root: Path, *, apply: bool) -> int:
    container = create_container()
    return container.uninstall_service().run_uninstall(project_root, apply=apply)


def _seed_ai_sync_dir(project_root: Path) -> None:
    """Create a realistic .ai-sync/ directory with sources, rules, and plan."""
    sources_dir = project_root / ".ai-sync" / "sources" / "base"
    sources_dir.mkdir(parents=True, exist_ok=True)
    (sources_dir / "README.md").write_text("source repo clone", encoding="utf-8")

    rules_dir = project_root / ".ai-sync" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    (rules_dir / "commit-conventions.md").write_text("# Commit rules\n", encoding="utf-8")

    (project_root / ".ai-sync" / "last-plan.yaml").write_text("actions: []\n", encoding="utf-8")
    (project_root / ".ai-sync" / "instructions.md").write_text("# Custom\n", encoding="utf-8")

# ---------------------------------------------------------------------------
# Text marker uninstall
# ---------------------------------------------------------------------------


def test_uninstall_removes_marker_block(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    target = tmp_path / ".gemini" / "GEMINI.md"
    spec = WriteSpec(
        file_path=target,
        format="text",
        target="ai-sync:mcp-instructions",
        value="## MCP\n\nUse work\n",
    )
    _track_write([spec], store)
    assert target.exists()
    assert "BEGIN ai-sync:mcp-instructions" in target.read_text(encoding="utf-8")

    _run_uninstall(tmp_path, apply=True)
    if target.exists():
        assert "BEGIN ai-sync:mcp-instructions" not in target.read_text(encoding="utf-8")


def test_uninstall_text_restores_baseline(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    target = tmp_path / "rules.mdc"
    target.parent.mkdir(parents=True, exist_ok=True)
    original_block = "<!-- BEGIN ai-sync:test -->\noriginal content\n<!-- END ai-sync:test -->"
    target.write_text(f"# Header\n\n{original_block}\n", encoding="utf-8")

    _track_write(
        [
            WriteSpec(file_path=target, format="text", target="ai-sync:test", value="replaced content"),
        ],
        store
    )
    assert "replaced content" in target.read_text(encoding="utf-8")

    _run_uninstall(tmp_path, apply=True)
    restored = target.read_text(encoding="utf-8")
    assert "original content" in restored
    assert "replaced content" not in restored


# ---------------------------------------------------------------------------
# Structured JSON uninstall
# ---------------------------------------------------------------------------


def test_uninstall_structured_json_roundtrip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    target = tmp_path / "config.json"
    _track_write(
        [
            WriteSpec(file_path=target, format="json", target="/settings/theme", value="dark"),
            WriteSpec(file_path=target, format="json", target="/settings/lang", value="en"),
        ],
        store
    )
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["settings"]["theme"] == "dark"
    assert data["settings"]["lang"] == "en"

    _run_uninstall(tmp_path, apply=True)
    data = json.loads(target.read_text(encoding="utf-8"))
    assert "theme" not in data.get("settings", {})
    assert "lang" not in data.get("settings", {})


def test_uninstall_structured_json_preserves_pre_existing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    target = tmp_path / "config.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('{"existing": true}', encoding="utf-8")

    _track_write(
        [
            WriteSpec(file_path=target, format="json", target="/added", value="new"),
        ],
        store
    )
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["existing"] is True
    assert data["added"] == "new"

    _run_uninstall(tmp_path, apply=True)
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data.get("existing") is True
    assert "added" not in data


def test_uninstall_structured_json_restores_overwritten_value(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    target = tmp_path / "config.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('{"key": "original"}', encoding="utf-8")

    _track_write(
        [
            WriteSpec(file_path=target, format="json", target="/key", value="replaced"),
        ],
        store
    )
    assert json.loads(target.read_text(encoding="utf-8"))["key"] == "replaced"

    _run_uninstall(tmp_path, apply=True)
    assert json.loads(target.read_text(encoding="utf-8"))["key"] == "original"


# ---------------------------------------------------------------------------
# Structured YAML uninstall
# ---------------------------------------------------------------------------


def test_uninstall_structured_yaml_roundtrip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    target = tmp_path / "config.yaml"
    _track_write(
        [
            WriteSpec(file_path=target, format="yaml", target="/servers/main/port", value=8080),
        ],
        store
    )
    data = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert data["servers"]["main"]["port"] == 8080

    _run_uninstall(tmp_path, apply=True)
    data = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert "port" not in data.get("servers", {}).get("main", {})


# ---------------------------------------------------------------------------
# Structured TOML uninstall
# ---------------------------------------------------------------------------


def test_uninstall_structured_toml_roundtrip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    target = tmp_path / "config.toml"
    _track_write(
        [
            WriteSpec(file_path=target, format="toml", target="/tool/name", value="ai-sync"),
        ],
        store
    )
    data = tomli.loads(target.read_text(encoding="utf-8"))
    assert data["tool"]["name"] == "ai-sync"

    _run_uninstall(tmp_path, apply=True)
    data = tomli.loads(target.read_text(encoding="utf-8"))
    assert "name" not in data.get("tool", {})


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


def test_uninstall_dry_run_does_not_modify(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    target = tmp_path / "config.json"
    _track_write(
        [
            WriteSpec(file_path=target, format="json", target="/key", value="val"),
        ],
        store
    )
    assert target.exists()
    content_before = target.read_text(encoding="utf-8")

    _run_uninstall(tmp_path, apply=False)
    assert target.read_text(encoding="utf-8") == content_before


# ---------------------------------------------------------------------------
# Empty state
# ---------------------------------------------------------------------------


def test_uninstall_empty_state_returns_zero(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    result = _run_uninstall(tmp_path, apply=True)
    assert result == 0


# ---------------------------------------------------------------------------
# Root-list JSON uninstall
# ---------------------------------------------------------------------------


def test_uninstall_structured_json_root_list(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    target = tmp_path / "list.json"
    _track_write(
        [
            WriteSpec(file_path=target, format="json", target="/", value=[]),
            WriteSpec(file_path=target, format="json", target="/0", value={"name": "alpha"}),
        ],
        store
    )
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data == [{"name": "alpha"}]

    _run_uninstall(tmp_path, apply=True)
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data == {}


# ---------------------------------------------------------------------------
# Effect restoration (chmod, empty effects)
# ---------------------------------------------------------------------------


def test_uninstall_restores_chmod_baseline(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    secret_path = tmp_path / "secret.json"
    secret_path.write_text("{}", encoding="utf-8")
    os.chmod(secret_path, 0o600)
    assert secret_path.stat().st_mode & 0o777 == 0o600

    state_dir = tmp_path / ".ai-sync" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    missing_env_file = tmp_path / ".ai-sync" / "env.does-not-exist"
    state = {
        "version": 2,
        "entries": [
            {
                "file_path": str(missing_env_file),
                "format": "text",
                "target": "ai-sync:env",
                "baseline": {"exists": False},
            }
        ],
        "effects": [
            {
                "effect_type": "chmod",
                "target": str(secret_path),
                "target_key": f"chmod:{secret_path}",
                "baseline": {"prior_mode": 0o644},
            }
        ],
    }
    (state_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")

    result = _run_uninstall(tmp_path, apply=True)
    assert result == 0
    assert secret_path.stat().st_mode & 0o777 == 0o644


def test_uninstall_with_no_effects_still_works(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    state_dir = tmp_path / ".ai-sync" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state = {"version": 2, "entries": [], "effects": []}
    (state_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")

    result = _run_uninstall(tmp_path, apply=True)
    assert result == 0


# ---------------------------------------------------------------------------
# .ai-sync/ directory removal
# ---------------------------------------------------------------------------


def test_uninstall_removes_ai_sync_directory(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    target = tmp_path / "config.json"
    _track_write(
        [WriteSpec(file_path=target, format="json", target="/key", value="val")],
        store,
    )
    _seed_ai_sync_dir(tmp_path)
    ai_sync_dir = tmp_path / ".ai-sync"
    assert ai_sync_dir.is_dir()
    assert (ai_sync_dir / "sources" / "base" / "README.md").exists()
    assert (ai_sync_dir / "rules" / "commit-conventions.md").exists()
    assert (ai_sync_dir / "last-plan.yaml").exists()
    assert (ai_sync_dir / "instructions.md").exists()

    result = _run_uninstall(tmp_path, apply=True)
    assert result == 0
    assert not ai_sync_dir.exists()


def test_uninstall_removes_ai_sync_directory_without_state(tmp_path: Path, monkeypatch) -> None:
    """Even when no state.json exists, .ai-sync/ should be cleaned up."""
    monkeypatch.setenv("HOME", str(tmp_path))
    _seed_ai_sync_dir(tmp_path)
    ai_sync_dir = tmp_path / ".ai-sync"
    assert ai_sync_dir.is_dir()

    result = _run_uninstall(tmp_path, apply=True)
    assert result == 0
    assert not ai_sync_dir.exists()


def test_uninstall_preserves_yaml_manifests(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    manifest = tmp_path / ".ai-sync.yaml"
    local_manifest = tmp_path / ".ai-sync.local.yaml"
    manifest.write_text("sources: {}\n", encoding="utf-8")
    local_manifest.write_text("sources: {}\n", encoding="utf-8")
    _seed_ai_sync_dir(tmp_path)

    result = _run_uninstall(tmp_path, apply=True)
    assert result == 0
    assert manifest.exists()
    assert local_manifest.exists()


# ---------------------------------------------------------------------------
# Empty client directory pruning
# ---------------------------------------------------------------------------


def test_uninstall_prunes_empty_client_dirs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    for name in (".cursor", ".codex", ".gemini", ".claude"):
        d = tmp_path / name / "rules"
        d.mkdir(parents=True, exist_ok=True)
    _seed_ai_sync_dir(tmp_path)

    result = _run_uninstall(tmp_path, apply=True)
    assert result == 0
    for name in (".cursor", ".codex", ".gemini", ".claude"):
        assert not (tmp_path / name).exists()


def test_uninstall_preserves_nonempty_client_dirs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cursor_dir = tmp_path / ".cursor" / "rules"
    cursor_dir.mkdir(parents=True, exist_ok=True)
    (cursor_dir / "user-rule.mdc").write_text("user content\n", encoding="utf-8")
    _seed_ai_sync_dir(tmp_path)

    result = _run_uninstall(tmp_path, apply=True)
    assert result == 0
    assert (cursor_dir / "user-rule.mdc").exists()


# ---------------------------------------------------------------------------
# Dry-run does not remove .ai-sync/ or client dirs
# ---------------------------------------------------------------------------


def test_uninstall_dry_run_preserves_ai_sync_dir(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _seed_ai_sync_dir(tmp_path)
    (tmp_path / ".cursor" / "rules").mkdir(parents=True, exist_ok=True)

    result = _run_uninstall(tmp_path, apply=False)
    assert result == 0
    assert (tmp_path / ".ai-sync").is_dir()
    assert (tmp_path / ".ai-sync" / "sources" / "base" / "README.md").exists()
    assert (tmp_path / ".cursor").is_dir()
