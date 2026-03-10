"""Tests for scoped project manifests."""

from pathlib import Path

import pytest
import yaml

from ai_sync.project import ProjectManifest, find_project_root, manifest_fingerprint, resolve_project_manifest, split_scoped_ref


def test_project_manifest_from_yaml(tmp_path: Path) -> None:
    data = {
        "sources": {
            "company": {"source": "github.com/acme/company-ai-sync", "version": "v1.2.0"},
            "frontend": {"source": "../frontend-ai-sync"},
        },
        "agents": ["company/agent-a"],
        "skills": ["frontend/skill-a"],
        "commands": ["company/c1.md"],
        "mcp-servers": ["company/srv1"],
        "settings": {"mode": "normal"},
    }
    (tmp_path / ".ai-sync.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")

    manifest = resolve_project_manifest(tmp_path)
    assert sorted(manifest.sources) == ["company", "frontend"]
    assert manifest.agents == ["company/agent-a"]
    assert manifest.skills == ["frontend/skill-a"]
    assert manifest.commands == ["company/c1.md"]
    assert manifest.mcp_servers == ["company/srv1"]
    assert manifest.settings == {"mode": "normal"}


def test_project_manifest_requires_scoped_refs() -> None:
    with pytest.raises(ValueError, match="Scoped reference"):
        ProjectManifest(
            sources={"company": {"source": "github.com/acme/company-ai-sync", "version": "v1.2.0"}},
            agents=["agent-a"],
        )


def test_project_manifest_requires_known_alias() -> None:
    with pytest.raises(ValueError, match="Unknown source alias"):
        ProjectManifest(
            sources={"company": {"source": "github.com/acme/company-ai-sync", "version": "v1.2.0"}},
            agents=["frontend/agent-a"],
        )


def test_project_manifest_rejects_invalid_alias() -> None:
    with pytest.raises(ValueError, match="Invalid source alias"):
        ProjectManifest(
            sources={"BadAlias": {"source": "github.com/acme/company-ai-sync", "version": "v1.2.0"}},
        )


def test_split_scoped_ref() -> None:
    assert split_scoped_ref("company/code-review") == ("company", "code-review")


def test_split_scoped_ref_rejects_invalid_values() -> None:
    with pytest.raises(ValueError):
        split_scoped_ref("company")


def test_find_project_root_walks_up(tmp_path: Path) -> None:
    project = tmp_path / "code" / "myproject"
    project.mkdir(parents=True)
    (project / ".ai-sync.yaml").write_text("sources: {}\n", encoding="utf-8")
    subdir = project / "src" / "deep"
    subdir.mkdir(parents=True)

    assert find_project_root(subdir) == project


def test_find_project_root_returns_none(tmp_path: Path) -> None:
    assert find_project_root(tmp_path) is None


def test_manifest_fingerprint_changes_with_content(tmp_path: Path) -> None:
    manifest_path = tmp_path / ".ai-sync.yaml"
    manifest_path.write_text("sources: {}\n", encoding="utf-8")
    first = manifest_fingerprint(manifest_path)
    manifest_path.write_text("sources:\n  company:\n    source: ../company\n", encoding="utf-8")
    assert manifest_fingerprint(manifest_path) != first


def test_no_ai_sync_yaml_raises(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="No .ai-sync.yaml"):
        resolve_project_manifest(tmp_path)
