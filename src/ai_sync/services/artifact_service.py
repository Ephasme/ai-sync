"""Service for collecting sync artifacts from resolved project inputs."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ai_sync.data_classes.artifact import Artifact
from ai_sync.data_classes.write_spec import WriteSpec
from ai_sync.models import split_scoped_ref
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

        def make_resolve(rules=list(manifest.rules), pr=project_root):
            def resolve():
                lines = [
                    "## ai-sync Rules (managed)\n",
                    "You MUST read and follow ALL rules listed below:\n",
                ]
                for rule_ref in rules:
                    alias, rule_name = split_scoped_ref(rule_ref)
                    prefixed = f"{alias}-{rule_name}"
                    rel_path = f".ai-sync/rules/{prefixed}.md"
                    lines.append(f"- [{rule_name}]({rel_path})")
                content = "\n".join(lines) + "\n"
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
