"""Tests for project manifest loading and resolution."""

from pathlib import Path

import yaml

from ai_sync.project import (
    ProjectManifest,
    _deep_merge_settings,
    find_project_root,
    load_defaults,
    resolve_project_manifest,
    validate_against_registry,
)


def test_project_manifest_from_yaml(tmp_path: Path) -> None:
    data = {
        "agents": ["a1", "a2"],
        "skills": ["s1"],
        "commands": ["c1.md"],
        "mcp-servers": ["srv1"],
        "settings": {"mode": "normal"},
    }
    ai_sync_yaml = tmp_path / ".ai-sync.yaml"
    ai_sync_yaml.write_text(yaml.safe_dump(data))

    manifest = resolve_project_manifest(tmp_path)
    assert manifest.agents == ["a1", "a2"]
    assert manifest.skills == ["s1"]
    assert manifest.commands == ["c1.md"]
    assert manifest.mcp_servers == ["srv1"]
    assert manifest.settings == {"mode": "normal"}


def test_local_replaces_list_keys(tmp_path: Path) -> None:
    base = {"agents": ["a1", "a2"], "skills": ["s1"], "mcp-servers": ["srv1"]}
    local = {"agents": ["a3"]}

    (tmp_path / ".ai-sync.yaml").write_text(yaml.safe_dump(base))
    (tmp_path / ".ai-sync.local.yaml").write_text(yaml.safe_dump(local))

    manifest = resolve_project_manifest(tmp_path)
    assert manifest.agents == ["a3"]
    assert manifest.skills == ["s1"]
    assert manifest.mcp_servers == ["srv1"]


def test_local_deep_merges_settings(tmp_path: Path) -> None:
    base = {"agents": [], "settings": {"mode": "normal", "experimental": True, "tools": {"sandbox": False}}}
    local = {"settings": {"mode": "yolo", "tools": {"sandbox": True}}}

    (tmp_path / ".ai-sync.yaml").write_text(yaml.safe_dump(base))
    (tmp_path / ".ai-sync.local.yaml").write_text(yaml.safe_dump(local))

    manifest = resolve_project_manifest(tmp_path)
    assert manifest.settings["mode"] == "yolo"
    assert manifest.settings["experimental"] is True
    assert manifest.settings["tools"]["sandbox"] is True


def test_settings_null_deletes_key() -> None:
    base = {"mode": "normal", "experimental": True}
    overlay = {"experimental": None}
    result = _deep_merge_settings(base, overlay)
    assert "experimental" not in result
    assert result["mode"] == "normal"


def test_find_project_root_walks_up(tmp_path: Path) -> None:
    project = tmp_path / "code" / "myproject"
    project.mkdir(parents=True)
    (project / ".ai-sync.yaml").write_text("agents: []")
    subdir = project / "src" / "deep"
    subdir.mkdir(parents=True)

    found = find_project_root(subdir)
    assert found == project


def test_find_project_root_returns_none(tmp_path: Path) -> None:
    found = find_project_root(tmp_path)
    assert found is None


def test_load_defaults_missing(tmp_path: Path) -> None:
    result = load_defaults(tmp_path)
    assert result == {}


def test_load_defaults_present(tmp_path: Path) -> None:
    defaults_dir = tmp_path / "config"
    defaults_dir.mkdir()
    defaults = {"agents": ["a1"], "settings": {"mode": "normal"}}
    (defaults_dir / "defaults.yaml").write_text(yaml.safe_dump(defaults))

    result = load_defaults(tmp_path)
    assert result["agents"] == ["a1"]


def test_validate_against_registry(tmp_path: Path) -> None:
    config_root = tmp_path / "registry"
    prompts_dir = config_root / "config" / "prompts"
    prompts_dir.mkdir(parents=True)
    (prompts_dir / "agent_a.md").write_text("content")

    skills_dir = config_root / "config" / "skills" / "skill-a"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text("content")

    mcp_dir = config_root / "config"
    (mcp_dir / "mcp-servers.yaml").write_text(yaml.safe_dump({"servers": {"srv1": {"method": "stdio", "command": "x"}}}))

    manifest = ProjectManifest(
        agents=["agent_a", "agent_b"],
        skills=["skill-a", "skill-x"],
        mcp_servers=["srv1", "srv2"],
    )
    warnings = validate_against_registry(manifest, config_root)
    assert any("agent_b" in w for w in warnings)
    assert any("skill-x" in w for w in warnings)
    assert any("srv2" in w for w in warnings)
    assert not any("agent_a" in w for w in warnings)
    assert not any("skill-a" in w for w in warnings)
    assert not any("srv1" in w for w in warnings)


def test_no_ai_sync_yaml_raises(tmp_path: Path) -> None:
    import pytest
    with pytest.raises(RuntimeError, match="No .ai-sync.yaml"):
        resolve_project_manifest(tmp_path)
