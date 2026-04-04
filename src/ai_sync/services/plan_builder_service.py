"""Service for building apply plans from resolved sources and artifacts."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ai_sync.clients import ClientFactory
from ai_sync.data_classes.artifact import Artifact
from ai_sync.data_classes.effect_spec import EffectSpec
from ai_sync.data_classes.resolved_artifact_set import ResolvedArtifactSet
from ai_sync.data_classes.write_spec import WriteSpec
from ai_sync.models import ApplyPlan, PlanAction, PlanSource
from ai_sync.services.artifact_service import ArtifactService
from ai_sync.services.git_safety_service import GitSafetyService
from ai_sync.services.managed_output_service import ManagedOutputService

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_sync.data_classes.apply_spec import ApplySpec
    from ai_sync.data_classes.prepared_artifacts import PreparedArtifacts
    from ai_sync.data_classes.resolved_source import ResolvedSource
    from ai_sync.data_classes.runtime_env import RuntimeEnv
    from ai_sync.models import ProjectManifest

_CLIENT_DIR_PREFIXES = (".cursor/", ".claude/", ".codex/", ".gemini/")


class PlanBuilderService:
    """Compute plan actions from current filesystem state and desired artifacts."""

    def __init__(
        self,
        *,
        artifact_service: ArtifactService,
        git_safety_service: GitSafetyService,
        managed_output_service: ManagedOutputService,
        client_factory: ClientFactory,
    ) -> None:
        self._artifact_service = artifact_service
        self._git_safety_service = git_safety_service
        self._managed_output_service = managed_output_service
        self._client_factory = client_factory

    def resolve_artifacts(
        self,
        *,
        project_root: Path,
        manifest: "ProjectManifest",
        resolved_sources: dict[str, "ResolvedSource"],
        runtime_env: "RuntimeEnv",
        prepared_artifacts: "PreparedArtifacts",
    ) -> ResolvedArtifactSet:
        clients = self._client_factory.create_clients(project_root)
        artifacts = list(
            self._artifact_service.collect_artifacts(
                project_root=project_root,
                manifest=manifest,
                resolved_sources=resolved_sources,
                runtime_env=runtime_env,
                prepared_artifacts=prepared_artifacts,
                clients=clients,
            )
        )
        artifacts.extend(
            self._git_safety_hook_artifacts(project_root, prepared_artifacts)
        )

        entries: list[tuple[Artifact, Sequence[ApplySpec]]] = []
        desired_targets: set[tuple[str, str, str]] = set()
        for artifact in artifacts:
            specs = artifact.resolve()
            entries.append((artifact, specs))
            for spec in specs:
                if isinstance(spec, WriteSpec):
                    desired_targets.add((str(spec.file_path), spec.format, spec.target))
        return ResolvedArtifactSet(entries=entries, desired_targets=desired_targets)

    def build_plan(
        self,
        project_root: Path,
        manifest_path: Path,
        manifest: "ProjectManifest",
        manifest_hash: str,
        resolved_sources: dict[str, "ResolvedSource"],
        runtime_env: "RuntimeEnv",
        prepared_artifacts: "PreparedArtifacts",
    ) -> tuple[ApplyPlan, ResolvedArtifactSet]:
        source_models = [
            PlanSource(
                alias=source.alias,
                source=source.source,
                version=source.version,
                kind=source.kind,
                fingerprint=source.fingerprint,
                portability_warning=source.portability_warning,
            )
            for source in resolved_sources.values()
        ]

        resolved_set = self.resolve_artifacts(
            project_root=project_root,
            manifest=manifest,
            resolved_sources=resolved_sources,
            runtime_env=runtime_env,
            prepared_artifacts=prepared_artifacts,
        )

        specs_by_plan_key: dict[str, list[WriteSpec]] = {}
        effects_by_plan_key: dict[str, list[EffectSpec]] = {}
        artifact_by_plan_key: dict[str, Artifact] = {}
        for artifact, specs in resolved_set.entries:
            artifact_by_plan_key[artifact.plan_key] = artifact
            for spec in specs:
                if isinstance(spec, WriteSpec):
                    specs_by_plan_key.setdefault(artifact.plan_key, []).append(spec)
                elif isinstance(spec, EffectSpec):
                    effects_by_plan_key.setdefault(artifact.plan_key, []).append(spec)

        actions: list[PlanAction] = []

        for plan_key, write_specs in specs_by_plan_key.items():
            status = self._managed_output_service.classify_plan_key_specs(
                project_root=project_root,
                specs=write_specs,
            )
            if status == "unchanged":
                continue
            art = artifact_by_plan_key[plan_key]
            target_path = write_specs[0].file_path if write_specs else plan_key
            actions.append(
                PlanAction(
                    action=status,
                    source_alias=art.source_alias,
                    kind=art.kind,
                    resource=art.resource,
                    name=art.name,
                    description=art.description,
                    target=str(target_path),
                    target_key=plan_key,
                    client=art.client,
                    secret_backed=art.secret_backed,
                )
            )

        for plan_key, effect_specs in effects_by_plan_key.items():
            art = artifact_by_plan_key[plan_key]
            for effect in effect_specs:
                effect_status = self._classify_effect(project_root, effect)
                if effect_status == "unchanged":
                    continue
                actions.append(
                    PlanAction(
                        action=effect_status,
                        source_alias=art.source_alias,
                        kind=art.kind,
                        resource=art.resource,
                        name=art.name,
                        description=art.description,
                        target=effect.target,
                        target_key=effect.target_key,
                        client=art.client,
                        secret_backed=art.secret_backed,
                    )
                )

        stale_actions = self._build_stale_plan_actions(
            self._managed_output_service.list_stale_entries(
                project_root=project_root,
                desired_targets=resolved_set.desired_targets,
            ),
            project_root,
        )
        actions.extend(stale_actions)

        selections = {
            "agents": manifest.agents,
            "skills": manifest.skills,
            "commands": manifest.commands,
            "rules": manifest.rules,
            "mcp_servers": manifest.mcp_servers,
        }

        plan = ApplyPlan(
            created_at=datetime.now(UTC).isoformat(),
            project_root=str(project_root),
            manifest_path=str(manifest_path),
            manifest_fingerprint=manifest_hash,
            sources=sorted(source_models, key=lambda item: item.alias),
            selections=selections,
            settings=manifest.settings,
            actions=actions,
        )
        return plan, resolved_set

    def _classify_effect(self, project_root: Path, effect: EffectSpec) -> str:
        """Classify an EffectSpec as create/update/delete/unchanged."""
        if effect.effect_type == "pre-commit-hook-install":
            status = self._git_safety_service.check_pre_commit_hook(project_root)
            return "unchanged" if status == "installed" else "create"
        if effect.effect_type == "pre-commit-hook-remove":
            status = self._git_safety_service.check_pre_commit_hook(project_root)
            return "delete" if status == "installed" else "unchanged"
        if effect.effect_type == "chmod":
            path = Path(effect.params.get("path", effect.target))
            if not path.exists():
                return "unchanged"
            return "update"
        return "unchanged"

    def _git_safety_hook_artifacts(
        self, project_root: Path, prepared_artifacts: "PreparedArtifacts"
    ) -> list[Artifact]:
        """Create git-safety hook artifacts as first-class EffectSpec producers."""
        if prepared_artifacts.has_env_file:

            def make_install_resolve() -> list[EffectSpec]:
                return [
                    EffectSpec(
                        effect_type="pre-commit-hook-install",
                        target=".git/hooks/pre-commit",
                        target_key="git-safety:pre-commit-hook",
                    )
                ]

            return [
                Artifact(
                    kind="git-safety",
                    resource="pre-commit hook",
                    name="pre-commit hook",
                    description="Git safety hook required for local secret handling.",
                    source_alias="project",
                    plan_key="git-safety:pre-commit-hook",
                    secret_backed=False,
                    client="global",
                    resolve_fn=make_install_resolve,
                )
            ]

        hook_status = self._git_safety_service.check_pre_commit_hook(project_root)
        if hook_status == "installed":

            def make_remove_resolve() -> list[EffectSpec]:
                return [
                    EffectSpec(
                        effect_type="pre-commit-hook-remove",
                        target=".git/hooks/pre-commit",
                        target_key="git-safety:pre-commit-hook",
                    )
                ]

            return [
                Artifact(
                    kind="git-safety",
                    resource="pre-commit hook",
                    name="pre-commit hook",
                    description="Remove ai-sync pre-commit hook when no local env vars are selected.",
                    source_alias="project",
                    plan_key="git-safety:pre-commit-hook",
                    secret_backed=False,
                    client="global",
                    resolve_fn=make_remove_resolve,
                )
            ]

        return []

    def _build_stale_plan_actions(
        self,
        stale_entries: list[dict],
        project_root: Path,
    ) -> list[PlanAction]:
        stale_actions: list[PlanAction] = []
        for entry in stale_entries:
            file_path = entry.get("file_path")
            target = entry.get("target")
            if not isinstance(file_path, str) or not isinstance(target, str):
                continue

            kind = entry.get("kind", "unknown")
            resource = entry.get("resource", target)
            name = entry.get("name", resource)
            description = entry.get("description", "")
            source_alias = entry.get("source_alias", "state")

            stale_actions.append(
                PlanAction(
                    action="delete",
                    source_alias=source_alias,
                    kind=kind,
                    resource=resource,
                    name=name if isinstance(name, str) else str(resource),
                    description=description if isinstance(description, str) else "",
                    target=file_path,
                    target_key=file_path,
                    client=_infer_client_from_path(file_path, str(project_root)),
                )
            )
        return stale_actions


def _infer_client_from_path(abs_path: str, project_root: str) -> str:
    """Derive the target client from a tracked file path for stale entries."""
    root = project_root.rstrip("/\\")
    rel = abs_path[len(root) + 1 :] if abs_path.startswith(root + "/") else abs_path
    for prefix in _CLIENT_DIR_PREFIXES:
        if rel.startswith(prefix):
            return prefix.strip("./")
    return "global"
