"""Tests for binary dependency parsing, collection, deduplication, and collision detection."""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_sync.models.env_dependency import parse_artifact_dependencies


# ---------------------------------------------------------------------------
# Parser: dependencies.binaries section
# ---------------------------------------------------------------------------


def test_parse_binaries_basic() -> None:
    result = parse_artifact_dependencies(
        {
            "binaries": [
                {"name": "npx", "version": {"require": "~10.0.0"}},
                {"name": "gh", "version": {"require": "^2.0.0", "get_cmd": "gh --version"}},
            ]
        },
        context="test",
    )
    assert len(result.binaries) == 2
    assert result.binaries[0].name == "npx"
    assert result.binaries[0].version.require == "~10.0.0"
    assert result.binaries[0].version.get_cmd is None
    assert result.binaries[1].name == "gh"
    assert result.binaries[1].version.get_cmd == "gh --version"
    assert result.env == {}


def test_parse_binaries_and_env_together() -> None:
    result = parse_artifact_dependencies(
        {
            "env": {"API_KEY": "abc123"},
            "binaries": [{"name": "uvx", "version": {"require": "^0.9.9"}}],
        },
        context="test",
    )
    assert len(result.env) == 1
    assert result.env["API_KEY"].literal == "abc123"
    assert len(result.binaries) == 1
    assert result.binaries[0].name == "uvx"


def test_parse_empty_dependencies() -> None:
    result = parse_artifact_dependencies({}, context="test")
    assert result.env == {}
    assert result.binaries == []


def test_parse_none_dependencies() -> None:
    result = parse_artifact_dependencies(None, context="test")
    assert result.env == {}
    assert result.binaries == []


def test_parse_missing_binaries_key() -> None:
    result = parse_artifact_dependencies({"env": {}}, context="test")
    assert result.binaries == []


def test_parse_empty_binaries_list() -> None:
    result = parse_artifact_dependencies({"binaries": []}, context="test")
    assert result.binaries == []


def test_parse_binaries_rejects_non_list() -> None:
    with pytest.raises(RuntimeError, match="dependencies.binaries must be a list"):
        parse_artifact_dependencies({"binaries": "bad"}, context="test")


def test_parse_binaries_rejects_non_mapping_entry() -> None:
    with pytest.raises(RuntimeError, match=r"dependencies\.binaries\[0\] must be a mapping"):
        parse_artifact_dependencies({"binaries": ["bad"]}, context="test")


def test_parse_binaries_rejects_invalid_version() -> None:
    with pytest.raises(RuntimeError, match=r"dependencies\.binaries\[0\] validation failed"):
        parse_artifact_dependencies(
            {"binaries": [{"name": "npx", "version": {"require": "10.0.0"}}]},
            context="test",
        )


def test_parse_rejects_unknown_dependency_key() -> None:
    with pytest.raises(RuntimeError, match="supports only 'env' and 'binaries'"):
        parse_artifact_dependencies({"env": {}, "extra": {}}, context="test")


# ---------------------------------------------------------------------------
# Collection via ArtifactBundleService
# ---------------------------------------------------------------------------


def _make_bundle(tmp_path: Path, kind: str, name: str, yaml_content: str) -> Path:
    bundle_dir = tmp_path / kind / name
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "artifact.yaml").write_text(yaml_content, encoding="utf-8")
    (bundle_dir / "prompt.md").write_text("test prompt", encoding="utf-8")
    return bundle_dir / "artifact.yaml"


def test_bundle_service_loads_binary_dependencies(tmp_path: Path) -> None:
    from ai_sync.services.artifact_bundle_service import ArtifactBundleService

    svc = ArtifactBundleService()
    _make_bundle(
        tmp_path,
        "mcp_servers",
        "test-server",
        (
            "name: test-server\n"
            "description: A test server\n"
            "dependencies:\n"
            "  binaries:\n"
            "    - name: npx\n"
            "      version:\n"
            "        require: ~10.0.0\n"
        ),
    )
    bundle = svc.load_artifact_yaml(
        tmp_path / "mcp_servers" / "test-server" / "artifact.yaml",
        defaults={},
        metadata_keys=None,
        required_keys={"name", "description"},
    )
    assert len(bundle.binary_dependencies) == 1
    assert bundle.binary_dependencies[0].name == "npx"
    assert bundle.binary_dependencies[0].version.require == "~10.0.0"


def test_bundle_service_loads_mixed_dependencies(tmp_path: Path) -> None:
    from ai_sync.services.artifact_bundle_service import ArtifactBundleService

    svc = ArtifactBundleService()
    _make_bundle(
        tmp_path,
        "skills",
        "my-skill",
        (
            "name: my-skill\n"
            "description: A skill\n"
            "dependencies:\n"
            "  env:\n"
            "    API_KEY: abc\n"
            "  binaries:\n"
            "    - name: gh\n"
            "      version:\n"
            "        require: ^2.0.0\n"
        ),
    )
    bundle = svc.load_artifact_yaml(
        tmp_path / "skills" / "my-skill" / "artifact.yaml",
        defaults={},
        metadata_keys=None,
        required_keys={"name", "description"},
    )
    assert len(bundle.env_dependencies) == 1
    assert "API_KEY" in bundle.env_dependencies
    assert len(bundle.binary_dependencies) == 1
    assert bundle.binary_dependencies[0].name == "gh"


# ---------------------------------------------------------------------------
# Deduplication and collision in ArtifactPreparationService
# ---------------------------------------------------------------------------


def _write_artifact(
    root: Path, kind: str, name: str, yaml_content: str, *, prompt: bool = True
) -> None:
    d = root / kind / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "artifact.yaml").write_text(yaml_content, encoding="utf-8")
    if prompt:
        (d / "prompt.md").write_text("test", encoding="utf-8")


def _prep_service():  # type: ignore[no-untyped-def]
    from unittest.mock import MagicMock

    from ai_sync.services.artifact_bundle_service import ArtifactBundleService
    from ai_sync.services.artifact_preparation_service import ArtifactPreparationService
    from ai_sync.services.mcp_preparation_service import McpPreparationService

    return ArtifactPreparationService(
        mcp_preparation_service=McpPreparationService(),
        artifact_bundle_service=ArtifactBundleService(),
        environment_service=MagicMock(),
    )


def _resolved_source(alias: str, root: Path):  # type: ignore[no-untyped-def]
    from ai_sync.data_classes.resolved_source import ResolvedSource

    return ResolvedSource(
        alias=alias, source=str(root), version=None, root=root, kind="local", fingerprint="abc"
    )


def _manifest(
    agents: list[str] | None = None,
    skills: list[str] | None = None,
    commands: list[str] | None = None,
    rules: list[str] | None = None,
    mcp_servers: list[str] | None = None,
):  # type: ignore[no-untyped-def]
    from unittest.mock import MagicMock

    m = MagicMock()
    m.agents = agents or []
    m.skills = skills or []
    m.commands = commands or []
    m.rules = rules or []
    m.mcp_servers = mcp_servers or []
    return m


def test_collect_deduplicates_identical_binary_deps(tmp_path: Path) -> None:
    src_a = tmp_path / "a"
    src_b = tmp_path / "b"
    for src in (src_a, src_b):
        _write_artifact(
            src,
            "skills",
            "my-skill",
            (
                "name: my-skill\n"
                "description: A skill\n"
                "dependencies:\n"
                "  binaries:\n"
                "    - name: npx\n"
                "      version:\n"
                "        require: ~10.0.0\n"
            ),
        )

    svc = _prep_service()
    resolved = {"a": _resolved_source("a", src_a), "b": _resolved_source("b", src_b)}
    manifest = _manifest(skills=["a/my-skill", "b/my-skill"])

    binaries = svc._collect_binary_dependencies(
        manifest=manifest, resolved_sources=resolved, mcp_source_configs={}
    )
    assert len(binaries) == 1
    assert binaries[0].name == "npx"


def test_collect_raises_on_conflicting_binary_versions(tmp_path: Path) -> None:
    src_a = tmp_path / "a"
    src_b = tmp_path / "b"
    _write_artifact(
        src_a,
        "skills",
        "skill-a",
        (
            "name: skill-a\n"
            "description: A\n"
            "dependencies:\n"
            "  binaries:\n"
            "    - name: npx\n"
            "      version:\n"
            "        require: ~10.0.0\n"
        ),
    )
    _write_artifact(
        src_b,
        "skills",
        "skill-b",
        (
            "name: skill-b\n"
            "description: B\n"
            "dependencies:\n"
            "  binaries:\n"
            "    - name: npx\n"
            "      version:\n"
            "        require: ^10.0.0\n"
        ),
    )

    svc = _prep_service()
    resolved = {"a": _resolved_source("a", src_a), "b": _resolved_source("b", src_b)}
    manifest = _manifest(skills=["a/skill-a", "b/skill-b"])

    with pytest.raises(RuntimeError, match="Binary dependency collision for 'npx'"):
        svc._collect_binary_dependencies(
            manifest=manifest, resolved_sources=resolved, mcp_source_configs={}
        )


def test_collect_binary_deps_from_mcp_servers(tmp_path: Path) -> None:
    from ai_sync.models.binary_dependency import BinaryDependency
    from ai_sync.models.binary_dependency_version import BinaryDependencyVersion

    svc = _prep_service()
    mcp_configs = {
        "my-server": {
            "_binary_dependencies": [
                BinaryDependency(
                    name="npx", version=BinaryDependencyVersion(require="~10.0.0")
                ),
            ],
        },
    }
    manifest = _manifest(mcp_servers=["src/my-server"])
    binaries = svc._collect_binary_dependencies(
        manifest=manifest, resolved_sources={"src": _resolved_source("src", tmp_path)},
        mcp_source_configs=mcp_configs,
    )
    assert len(binaries) == 1
    assert binaries[0].name == "npx"


def test_collect_binary_deps_across_artifact_kinds(tmp_path: Path) -> None:
    src = tmp_path / "src"
    _write_artifact(
        src,
        "agents",
        "my-agent",
        (
            "name: my-agent\n"
            "description: An agent\n"
            "dependencies:\n"
            "  binaries:\n"
            "    - name: npx\n"
            "      version:\n"
            "        require: ~10.0.0\n"
        ),
    )
    _write_artifact(
        src,
        "rules",
        "my-rule",
        (
            "name: my-rule\n"
            "description: A rule\n"
            "dependencies:\n"
            "  binaries:\n"
            "    - name: gh\n"
            "      version:\n"
            "        require: ^2.0.0\n"
        ),
    )

    svc = _prep_service()
    resolved = {"src": _resolved_source("src", src)}
    manifest = _manifest(agents=["src/my-agent"], rules=["src/my-rule"])

    binaries = svc._collect_binary_dependencies(
        manifest=manifest, resolved_sources=resolved, mcp_source_configs={}
    )
    names = sorted(b.name for b in binaries)
    assert names == ["gh", "npx"]
