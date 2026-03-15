"""Service for discovering available artifacts in resolved sources."""

from __future__ import annotations

from pathlib import Path

from ai_sync.data_classes.resolved_source import ResolvedSource
from ai_sync.data_classes.source_catalog_entry import SourceCatalogEntry
from ai_sync.helpers import mcp_description, to_kebab_case
from ai_sync.models import ProjectManifest
from ai_sync.services.artifact_bundle_service import (
    BUNDLE_ARTIFACT_FILENAME,
    ArtifactBundleService,
)

_RESOURCE_KINDS: tuple[tuple[str, str], ...] = (
    ("prompts", "agent"),
    ("skills", "skill"),
    ("commands", "command"),
    ("rules", "rule"),
    ("mcp-servers", "mcp-server"),
)


class SourceCatalogService:
    """Discover all available artifacts in resolved sources."""

    def __init__(self, *, artifact_bundle_service: ArtifactBundleService) -> None:
        self._artifact_bundle_service = artifact_bundle_service

    def catalog_source(
        self,
        *,
        source: ResolvedSource,
        manifest: ProjectManifest,
    ) -> list[SourceCatalogEntry]:
        selected_refs = set(manifest.iter_all_resource_refs())
        entries: list[SourceCatalogEntry] = []
        for directory_name, kind in _RESOURCE_KINDS:
            entries.extend(
                self._catalog_directory(
                    source=source,
                    manifest=manifest,
                    selected_refs=selected_refs,
                    directory_name=directory_name,
                    kind=kind,
                )
            )
        return entries

    def catalog_sources(
        self,
        *,
        resolved_sources: dict[str, ResolvedSource],
        manifest: ProjectManifest,
    ) -> dict[str, list[SourceCatalogEntry]]:
        return {
            alias: self.catalog_source(source=source, manifest=manifest)
            for alias, source in resolved_sources.items()
        }

    def _catalog_directory(
        self,
        *,
        source: ResolvedSource,
        manifest: ProjectManifest,
        selected_refs: set[str],
        directory_name: str,
        kind: str,
    ) -> list[SourceCatalogEntry]:
        base_dir = source.root / directory_name
        if not base_dir.is_dir():
            return []

        entries: list[SourceCatalogEntry] = []
        for artifact_path in sorted(base_dir.rglob(BUNDLE_ARTIFACT_FILENAME)):
            resource_id = artifact_path.relative_to(base_dir).parent.as_posix()
            scoped_ref = f"{source.alias}/{resource_id}"
            bundle = self._artifact_bundle_service.load_artifact_yaml(
                artifact_path,
                defaults=self._defaults_for_kind(kind, Path(resource_id)),
                metadata_keys=None,
                required_keys={"name", "description"},
            )
            description = self._description_for_entry(kind, bundle.metadata)
            entries.append(
                SourceCatalogEntry(
                    kind=kind,
                    resource_id=resource_id,
                    scoped_ref=scoped_ref,
                    name=str(bundle.metadata.get("name") or Path(resource_id).name),
                    description=description,
                    selected=scoped_ref in selected_refs,
                )
            )
        return entries

    def _defaults_for_kind(self, kind: str, resource_path: Path) -> dict[str, object]:
        if kind == "agent":
            return {"slug": to_kebab_case(resource_path.name)}
        return {}

    def _description_for_entry(self, kind: str, metadata: dict[str, object]) -> str:
        description = metadata.get("description")
        if isinstance(description, str) and description:
            return description
        if kind != "mcp-server":
            return ""
        return mcp_description(metadata, "MCP server")
