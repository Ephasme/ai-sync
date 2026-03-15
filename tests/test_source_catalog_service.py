from __future__ import annotations

from pathlib import Path

from ai_sync.data_classes.resolved_source import ResolvedSource
from ai_sync.models import ProjectManifest, SourceConfig
from ai_sync.services.artifact_bundle_service import ArtifactBundleService
from ai_sync.services.source_catalog_service import SourceCatalogService


def _write_source(root: Path) -> None:
    (root / "prompts" / "engineer").mkdir(parents=True)
    (root / "prompts" / "engineer" / "artifact.yaml").write_text(
        "slug: engineer\n"
        "name: Engineer\n"
        "description: Senior software engineer assistant\n",
        encoding="utf-8",
    )
    (root / "prompts" / "engineer" / "prompt.md").write_text("## Task\nHelp\n", encoding="utf-8")

    (root / "skills" / "code-review").mkdir(parents=True)
    (root / "skills" / "code-review" / "artifact.yaml").write_text(
        "name: code-review\n"
        "description: Review code skill\n",
        encoding="utf-8",
    )
    (root / "skills" / "code-review" / "prompt.md").write_text("# Skill\n", encoding="utf-8")

    (root / "commands" / "review" / "summary").mkdir(parents=True)
    (root / "commands" / "review" / "summary" / "artifact.yaml").write_text(
        "name: Review summary\n"
        "description: Review summary command\n",
        encoding="utf-8",
    )
    (root / "commands" / "review" / "summary" / "prompt.md").write_text(
        "Summarize review\n",
        encoding="utf-8",
    )

    (root / "rules" / "commit").mkdir(parents=True)
    (root / "rules" / "commit" / "artifact.yaml").write_text(
        "name: Commit conventions\n"
        "description: Commit conventions\n"
        "alwaysApply: true\n",
        encoding="utf-8",
    )
    (root / "rules" / "commit" / "prompt.md").write_text("Commit rules\n", encoding="utf-8")

    (root / "mcp-servers" / "context7").mkdir(parents=True)
    (root / "mcp-servers" / "context7" / "artifact.yaml").write_text(
        "name: Context7\n"
        "description: Library documentation lookup via Context7.\n"
        "method: stdio\n"
        "command: npx\n",
        encoding="utf-8",
    )


def _resolved_source(alias: str, root: Path) -> ResolvedSource:
    return ResolvedSource(
        alias=alias,
        source=str(root),
        version=None,
        root=root,
        kind="local",
        fingerprint="test",
    )


def test_catalog_source_lists_available_artifacts_and_selection_state(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _write_source(source_root)
    service = SourceCatalogService(artifact_bundle_service=ArtifactBundleService())
    manifest = ProjectManifest(
        sources={"company": SourceConfig(source=str(source_root))},
        agents=["company/engineer"],
        commands=["company/review/summary"],
        mcp_servers=["company/context7"],
    )

    entries = service.catalog_source(
        source=_resolved_source("company", source_root),
        manifest=manifest,
    )

    by_ref = {entry.scoped_ref: entry for entry in entries}
    assert set(by_ref) == {
        "company/engineer",
        "company/code-review",
        "company/review/summary",
        "company/commit",
        "company/context7",
    }
    assert by_ref["company/engineer"].selected is True
    assert by_ref["company/review/summary"].selected is True
    assert by_ref["company/code-review"].selected is False
    assert by_ref["company/commit"].selected is False
    assert by_ref["company/context7"].selected is True
    assert by_ref["company/review/summary"].name == "Review summary"
    assert by_ref["company/commit"].name == "Commit conventions"
    assert by_ref["company/context7"].name == "Context7"


def test_catalog_source_reads_mcp_description(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _write_source(source_root)
    service = SourceCatalogService(artifact_bundle_service=ArtifactBundleService())
    manifest = ProjectManifest(
        sources={"company": SourceConfig(source=str(source_root))},
    )

    entries = service.catalog_source(
        source=_resolved_source("company", source_root),
        manifest=manifest,
    )

    context7 = next(entry for entry in entries if entry.scoped_ref == "company/context7")
    assert context7.kind == "mcp-server"
    assert context7.name == "Context7"
    assert context7.description == "Library documentation lookup via Context7."
