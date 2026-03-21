"""Service for collecting agent artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ai_sync.data_classes.artifact import Artifact
from ai_sync.helpers import string_metadata_value, to_kebab_case
from ai_sync.models import split_scoped_ref
from ai_sync.services.artifact_bundle_service import ArtifactBundleService

if TYPE_CHECKING:
    from ai_sync.clients.base import Client
    from ai_sync.data_classes.prepared_artifacts import PreparedArtifacts
    from ai_sync.data_classes.resolved_source import ResolvedSource
    from ai_sync.data_classes.runtime_env import RuntimeEnv
    from ai_sync.models import ProjectManifest
class AgentArtifactService:
    """Build `Artifact` entries for selected agent bundles."""

    def __init__(self, *, artifact_bundle_service: ArtifactBundleService) -> None:
        self._artifact_bundle_service = artifact_bundle_service

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
        del project_root, runtime_env, prepared_artifacts

        artifacts: list[Artifact] = []
        for agent_ref in manifest.agents:
            alias, agent_name = split_scoped_ref(agent_ref)
            agent_rel = Path(agent_name)
            artifact_path = self._artifact_bundle_service.bundle_entry_path(
                resolved_sources[alias].root / "prompts",
                agent_rel,
            )
            if not artifact_path.exists():
                raise RuntimeError(f"Selected agent {agent_ref!r} was not found.")

            bundle = self._artifact_bundle_service.load_artifact_yaml(
                artifact_path,
                defaults={
                    "slug": to_kebab_case(agent_rel.name),
                },
                metadata_keys={"slug", "name", "description"},
                required_keys={"name", "description"},
            )
            slug = str(bundle.metadata.get("slug") or to_kebab_case(agent_rel.name))
            artifact_name = string_metadata_value(
                bundle.metadata.get("name"),
                to_kebab_case(agent_rel.name),
            )
            artifact_description = string_metadata_value(
                bundle.metadata.get("description"),
                "",
            )

            for client in clients:
                prefixed_slug = f"{alias}-{slug}"

                def make_resolve(
                    p: Path = artifact_path,
                    c: Client = client,
                    a: str = alias,
                    rel: Path = agent_rel,
                ):
                    def resolve():
                        bundle = self._artifact_bundle_service.load_artifact_yaml(
                            p,
                            defaults={
                                "slug": to_kebab_case(rel.name),
                            },
                            metadata_keys={"slug", "name", "description"},
                            required_keys={"name", "description"},
                        )
                        raw_content = self._artifact_bundle_service.require_prompt(bundle, p)
                        slug_value = str(
                            bundle.metadata.get("slug") or to_kebab_case(rel.name)
                        )
                        return c.build_agent_specs(
                            a,
                            slug_value,
                            bundle.metadata,
                            raw_content,
                            self._artifact_bundle_service.bundle_prompt_path(p),
                        )

                    return resolve

                if client.name == "codex":
                    target = client.get_agents_dir() / prefixed_slug
                else:
                    target = client.get_agents_dir() / f"{prefixed_slug}.md"

                artifacts.append(
                    Artifact(
                        kind="agent",
                        resource=agent_ref,
                        name=artifact_name,
                        description=artifact_description,
                        source_alias=alias,
                        plan_key=str(target),
                        secret_backed=any(
                            dep.mode == "secret"
                            for dep in bundle.env_dependencies.values()
                        ),
                        client=client.name,
                        resolve_fn=make_resolve(),
                        env_dependencies=bundle.env_dependencies,
                    )
                )
        return artifacts
