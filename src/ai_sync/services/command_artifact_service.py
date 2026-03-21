"""Service for collecting command artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ai_sync.data_classes.artifact import Artifact
from ai_sync.helpers import string_metadata_value
from ai_sync.models import split_scoped_ref
from ai_sync.services.artifact_bundle_service import ArtifactBundleService

if TYPE_CHECKING:
    from ai_sync.clients.base import Client
    from ai_sync.data_classes.prepared_artifacts import PreparedArtifacts
    from ai_sync.data_classes.resolved_source import ResolvedSource
    from ai_sync.data_classes.runtime_env import RuntimeEnv
    from ai_sync.models import ProjectManifest
def _command_target_path(client: "Client", alias: str, command_rel: Path) -> Path:
    if client.name == "gemini":
        return client.config_dir / "commands" / command_rel.with_name(
            f"{alias}-{command_rel.name}.toml"
        )
    return client.config_dir / "commands" / command_rel.with_name(
        f"{alias}-{command_rel.name}.md"
    )


class CommandArtifactService:
    """Build `Artifact` entries for selected command bundles."""

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
        for command_ref in manifest.commands:
            alias, command_name = split_scoped_ref(command_ref)
            command_rel = Path(command_name)
            command_path = self._artifact_bundle_service.bundle_entry_path(
                resolved_sources[alias].root / "commands",
                command_rel,
            )
            if not command_path.is_file():
                raise RuntimeError(f"Selected command {command_ref!r} was not found.")
            bundle = self._artifact_bundle_service.load_artifact_yaml(
                command_path,
                defaults={},
                metadata_keys={"name", "description"},
                required_keys={"name", "description"},
            )
            artifact_name = string_metadata_value(bundle.metadata.get("name"), command_rel.name)
            artifact_description = string_metadata_value(
                bundle.metadata.get("description"),
                "",
            )

            for client in clients:

                def make_resolve(
                    p: Path = command_path,
                    c: Client = client,
                    a: str = alias,
                    ref: str = command_ref,
                    name: str = command_rel.as_posix(),
                ):
                    def resolve():
                        bundle = self._artifact_bundle_service.load_artifact_yaml(
                            p,
                            defaults={},
                            metadata_keys={"name", "description"},
                            required_keys={"name", "description"},
                        )
                        raw_content = self._artifact_bundle_service.require_prompt(bundle, p)
                        return c.build_command_specs(
                            a,
                            ref,
                            bundle.metadata,
                            raw_content,
                            name,
                        )

                    return resolve

                target = _command_target_path(client, alias, command_rel)
                artifacts.append(
                    Artifact(
                        kind="command",
                        resource=command_ref,
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
