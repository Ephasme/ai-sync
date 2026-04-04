"""Service for collecting sync artifacts from resolved project inputs."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ai_sync.data_classes.artifact import Artifact
from ai_sync.data_classes.write_spec import WriteSpec
from ai_sync.services.artifact_collector_service import ArtifactCollectorService

if TYPE_CHECKING:
    from ai_sync.clients.base import Client
    from ai_sync.data_classes.prepared_artifacts import PreparedArtifacts
    from ai_sync.data_classes.resolved_source import ResolvedSource
    from ai_sync.data_classes.runtime_env import RuntimeEnv
    from ai_sync.models import ProjectManifest


class ArtifactService:
    """Build `Artifact` entries for all selected project resources."""

    def __init__(
        self,
        *,
        agent_artifact_service: ArtifactCollectorService,
        command_artifact_service: ArtifactCollectorService,
        skill_artifact_service: ArtifactCollectorService,
        rule_artifact_service: ArtifactCollectorService,
        mcp_artifact_service: ArtifactCollectorService,
        project_artifact_service: ArtifactCollectorService,
    ) -> None:
        self._agent_artifact_service = agent_artifact_service
        self._command_artifact_service = command_artifact_service
        self._skill_artifact_service = skill_artifact_service
        self._rule_artifact_service = rule_artifact_service
        self._mcp_artifact_service = mcp_artifact_service
        self._project_artifact_service = project_artifact_service

    def collect_artifacts(
        self,
        *,
        project_root: Path,
        manifest: "ProjectManifest",
        resolved_sources: dict[str, "ResolvedSource"],
        runtime_env: "RuntimeEnv",
        prepared_artifacts: "PreparedArtifacts",
        clients: list["Client"],
    ) -> list[Artifact]:
        return [
            *self._agent_artifact_service.collect_artifacts(
                project_root=project_root,
                manifest=manifest,
                resolved_sources=resolved_sources,
                runtime_env=runtime_env,
                prepared_artifacts=prepared_artifacts,
                clients=clients,
            ),
            *self._command_artifact_service.collect_artifacts(
                project_root=project_root,
                manifest=manifest,
                resolved_sources=resolved_sources,
                runtime_env=runtime_env,
                prepared_artifacts=prepared_artifacts,
                clients=clients,
            ),
            *self._skill_artifact_service.collect_artifacts(
                project_root=project_root,
                manifest=manifest,
                resolved_sources=resolved_sources,
                runtime_env=runtime_env,
                prepared_artifacts=prepared_artifacts,
                clients=clients,
            ),
            *self._rule_artifact_service.collect_artifacts(
                project_root=project_root,
                manifest=manifest,
                resolved_sources=resolved_sources,
                runtime_env=runtime_env,
                prepared_artifacts=prepared_artifacts,
                clients=clients,
            ),
            *self._rule_index_artifacts(manifest=manifest, project_root=project_root),
            *self._claude_md_artifacts(project_root=project_root),
            *self._mcp_artifact_service.collect_artifacts(
                project_root=project_root,
                manifest=manifest,
                resolved_sources=resolved_sources,
                runtime_env=runtime_env,
                prepared_artifacts=prepared_artifacts,
                clients=clients,
            ),
            *self._project_artifact_service.collect_artifacts(
                project_root=project_root,
                manifest=manifest,
                resolved_sources=resolved_sources,
                runtime_env=runtime_env,
                prepared_artifacts=prepared_artifacts,
                clients=clients,
            ),
        ]

    _RULES_INDEX_BODY = (
        "## ai-sync Rules (managed)\n"
        "\n"
        "You MUST read and follow ALL rule files in the `.ai-sync/rules/` directory.\n"
    )

    def _rule_index_artifacts(
        self,
        *,
        manifest: "ProjectManifest",
        project_root: Path,
    ) -> list[Artifact]:
        if not manifest.rules:
            return []

        agents_md = project_root / "AGENTS.md"
        marker_id = "ai-sync:rules-index"
        body = self._RULES_INDEX_BODY

        def make_resolve(pr: Path = project_root, content: str = body):
            def resolve():
                return [
                    WriteSpec(
                        file_path=pr / "AGENTS.md",
                        format="text",
                        target=marker_id,
                        value=content,
                    )
                ]

            return resolve

        return [
            Artifact(
                kind="rule-index",
                resource="ai-sync:rules-index",
                name="Rules index",
                description="Managed AGENTS.md links for selected rules.",
                source_alias="project",
                plan_key=f"{agents_md}#{marker_id}",
                secret_backed=False,
                client="global",
                resolve_fn=make_resolve(),
            )
        ]

    _CLAUDE_MD_BODY = "@AGENTS.md\n"

    def _claude_md_artifacts(self, *, project_root: Path) -> list[Artifact]:
        """Generate a gitignored CLAUDE.md that imports AGENTS.md for Claude Code."""
        claude_md = project_root / "CLAUDE.md"
        marker_id = "ai-sync:claude-import"
        body = self._CLAUDE_MD_BODY

        def make_resolve(pr: Path = project_root, content: str = body):
            def resolve():
                return [
                    WriteSpec(
                        file_path=pr / "CLAUDE.md",
                        format="text",
                        target=marker_id,
                        value=content,
                    )
                ]

            return resolve

        return [
            Artifact(
                kind="claude-import",
                resource="CLAUDE.md",
                name="CLAUDE.md import",
                description="Gitignored CLAUDE.md that imports AGENTS.md for Claude Code.",
                source_alias="project",
                plan_key=str(claude_md),
                secret_backed=False,
                client="global",
                resolve_fn=make_resolve(),
            )
        ]
