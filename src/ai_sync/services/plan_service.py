"""Service for plan context assembly and the plan command."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ai_sync.data_classes.plan_context import PlanContext
from ai_sync.services.artifact_preparation_service import ArtifactPreparationService
from ai_sync.services.config_store_service import ConfigStoreService
from ai_sync.services.display_service import DisplayService
from ai_sync.services.plan_builder_service import PlanBuilderService
from ai_sync.services.plan_persistence_service import PlanPersistenceService
from ai_sync.services.project_locator_service import ProjectLocatorService
from ai_sync.services.project_manifest_service import ProjectManifestService
from ai_sync.services.source_resolver_service import SourceResolverService
from ai_sync.services.tool_requirement_service import ToolRequirementService
from ai_sync.services.tool_version_service import ToolVersionService

if TYPE_CHECKING:
    pass


class PlanService:
    """Assemble plan context and handle the plan command."""

    def __init__(
        self,
        *,
        source_resolver_service: SourceResolverService,
        artifact_preparation_service: ArtifactPreparationService,
        project_locator_service: ProjectLocatorService,
        project_manifest_service: ProjectManifestService,
        tool_requirement_service: ToolRequirementService,
        plan_builder_service: PlanBuilderService,
        plan_persistence_service: PlanPersistenceService,
        config_store_service: ConfigStoreService,
        tool_version_service: ToolVersionService,
        validate_client_settings_fn: Callable[[dict[str, Any]], list[str]] | None = None,
    ) -> None:
        from ai_sync.helpers import validate_client_settings

        self._source_resolver_service = source_resolver_service
        self._artifact_preparation_service = artifact_preparation_service
        self._project_locator_service = project_locator_service
        self._project_manifest_service = project_manifest_service
        self._tool_requirement_service = tool_requirement_service
        self._plan_builder_service = plan_builder_service
        self._plan_persistence_service = plan_persistence_service
        self._config_store_service = config_store_service
        self._tool_version_service = tool_version_service
        self._validate_client_settings = validate_client_settings_fn or validate_client_settings

    def run(self, *, config_root: Path, display: DisplayService, out: str | None) -> int:
        """Execute the plan command: assemble context, render, and save."""
        prepared = self._prepare_project_context(config_root=config_root, display=display)
        if prepared is None:
            return 1
        project_root, plan_context = prepared

        self._plan_persistence_service.render_plan(plan_context.plan, display)
        out_path = (
            Path(out).expanduser()
            if out
            else self._plan_persistence_service.default_plan_path(project_root)
        )
        self._plan_persistence_service.save_plan(plan_context.plan, out_path)
        display.print(f"Saved plan to {out_path}", style="success")
        return 0

    def assemble_plan_context(
        self, project_root: Path, config_root: Path | None, display: DisplayService
    ) -> PlanContext:
        """Build PlanContext inputs and delegate action planning to PlanBuilderService."""
        manifest_path = self._project_manifest_service.resolve_project_manifest_path(project_root)
        manifest = self._project_manifest_service.resolve_project_manifest(project_root)
        manifest_hash = self._project_manifest_service.manifest_fingerprint(manifest_path)
        resolved_sources = self._source_resolver_service.resolve_sources(project_root, manifest)

        errors = self._validate_client_settings(manifest.settings)
        if errors:
            raise RuntimeError("\n".join(errors))

        req_results = self._tool_requirement_service.check_requirements(
            self._tool_requirement_service.load_and_filter_requirements(
                resolved_sources,
                manifest.mcp_servers,
                display,
            )
        )
        for result in req_results:
            if not result.ok and result.error:
                display.print(f"Warning: {result.error}", style="warning")

        prepared_artifacts, runtime_env = self._artifact_preparation_service.prepare(
            project_root=project_root,
            manifest=manifest,
            resolved_sources=resolved_sources,
            config_root=config_root,
            display=display,
        )

        plan, resolved_artifact_set = self._plan_builder_service.build_plan(
            project_root,
            manifest_path,
            manifest,
            manifest_hash,
            resolved_sources,
            runtime_env,
            prepared_artifacts,
        )
        return PlanContext(
            plan=plan,
            manifest=manifest,
            resolved_sources=resolved_sources,
            prepared_artifacts=prepared_artifacts,
            runtime_env=runtime_env,
            secrets={"servers": {}},
            resolved_artifacts=resolved_artifact_set,
        )

    def _prepare_project_context(
        self,
        *,
        config_root: Path,
        display: DisplayService,
    ) -> tuple[Path, PlanContext] | None:
        if not self._ensure_installed(config_root, display):
            return None

        project_root = self._project_locator_service.find_project_root()
        if project_root is None:
            display.panel(
                "No .ai-sync.local.yaml or .ai-sync.yaml found. Create one first.",
                title="No project",
                style="error",
            )
            return None

        self._warn_on_client_version_drift(display)
        context = self.assemble_plan_context(project_root, config_root, display)
        return (project_root, context)

    def _ensure_installed(self, config_root: Path, display: DisplayService) -> bool:
        if config_root.exists() and (config_root / "config.toml").exists():
            return True
        display.panel("Run `ai-sync install` first.", title="Not set up", style="error")
        return False

    def _warn_on_client_version_drift(self, display: DisplayService) -> None:
        versions_path = self._tool_version_service.get_default_versions_path()
        ok, message = self._tool_version_service.check_client_versions(versions_path)
        if not ok or message != "OK":
            display.print(f"Warning: {message}", style="warning")
