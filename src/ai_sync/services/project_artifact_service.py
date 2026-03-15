"""Service for collecting project-generated artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ai_sync.data_classes.artifact import Artifact
from ai_sync.data_classes.write_spec import WriteSpec
from ai_sync.services.git_safety_service import SENSITIVE_PATHS

if TYPE_CHECKING:
    from ai_sync.clients.base import Client
    from ai_sync.data_classes.resolved_source import ResolvedSource
    from ai_sync.data_classes.runtime_env import RuntimeEnv
    from ai_sync.models import ProjectManifest


class ProjectArtifactService:
    """Build project-local `Artifact` entries synthesized from runtime inputs."""

    def collect_artifacts(
        self,
        *,
        project_root: Path,
        manifest: "ProjectManifest",
        resolved_sources: dict[str, "ResolvedSource"],
        runtime_env: "RuntimeEnv",
        mcp_manifest: dict,
        clients: list["Client"],
    ) -> list[Artifact]:
        del resolved_sources, mcp_manifest

        return [
            *self._env_artifacts(project_root, runtime_env),
            *self._settings_artifacts(manifest, clients),
            *self._instructions_artifacts(project_root, clients),
            *self._gitignore_artifacts(project_root),
        ]

    def _env_artifacts(self, project_root: Path, runtime_env: "RuntimeEnv") -> list[Artifact]:
        if not runtime_env.env and not runtime_env.local_vars:
            return []
        env_path = project_root / ".env.ai-sync"

        def make_resolve(re=runtime_env, ep=env_path):
            def resolve():
                all_keys = set(re.env.keys()) | set(re.local_vars.keys())
                lines = [f"{key}={re.env.get(key, '')}" for key in sorted(all_keys)]
                content = "\n".join(lines) + "\n"
                return [WriteSpec(file_path=ep, format="text", target="ai-sync:env", value=content)]

            return resolve

        return [
            Artifact(
                kind="env-file",
                resource=".env.ai-sync",
                name=".env.ai-sync",
                description="Project-local environment values resolved by ai-sync.",
                source_alias="project",
                plan_key=str(env_path),
                secret_backed=True,
                client="global",
                resolve_fn=make_resolve(),
            )
        ]

    def _settings_artifacts(
        self,
        manifest: "ProjectManifest",
        clients: list["Client"],
    ) -> list[Artifact]:
        if not manifest.settings:
            return []
        artifacts: list[Artifact] = []
        for client in clients:

            def make_resolve(c: Client = client, s: dict = manifest.settings):
                def resolve():
                    return c.build_client_config_specs(s)

                return resolve

            specs = client.build_client_config_specs(manifest.settings)
            if not specs:
                continue
            target_file = specs[0].file_path
            artifacts.append(
                Artifact(
                    kind="client-settings",
                    resource=client.name,
                    name=f"{client.name} settings",
                    description=f"Managed {client.name} client configuration.",
                    source_alias="project",
                    plan_key=f"{target_file}#settings",
                    secret_backed=False,
                    client=client.name,
                    resolve_fn=make_resolve(),
                )
            )
        return artifacts

    def _instructions_artifacts(
        self,
        project_root: Path,
        clients: list["Client"],
    ) -> list[Artifact]:
        instructions_path = project_root / ".ai-sync" / "instructions.md"
        if not instructions_path.exists():
            return []
        content = instructions_path.read_text(encoding="utf-8")
        if not content.strip():
            return []

        artifacts: list[Artifact] = []
        for client in clients:

            def make_resolve(c: Client = client, ip: Path = instructions_path):
                def resolve():
                    text = ip.read_text(encoding="utf-8")
                    return c.build_instructions_specs(text)

                return resolve

            specs = client.build_instructions_specs(content)
            if not specs:
                continue
            target_file = specs[0].file_path
            artifacts.append(
                Artifact(
                    kind="instructions",
                    resource=client.name,
                    name=f"{client.name} instructions",
                    description=f"Managed project instructions for {client.name}.",
                    source_alias="project",
                    plan_key=f"{target_file}#instructions",
                    secret_backed=False,
                    client=client.name,
                    resolve_fn=make_resolve(),
                )
            )
        return artifacts

    def _gitignore_artifacts(self, project_root: Path) -> list[Artifact]:
        gitignore_path = project_root / ".gitignore"
        marker_id = "ai-sync:gitignore"

        def make_resolve(gp=gitignore_path):
            def resolve():
                content = "\n".join(SENSITIVE_PATHS) + "\n"
                return [WriteSpec(file_path=gp, format="text", target=marker_id, value=content)]

            return resolve

        return [
            Artifact(
                kind="git-safety",
                resource=".gitignore entries",
                name=".gitignore safety entries",
                description="Managed sensitive-path entries for git safety.",
                source_alias="project",
                plan_key=f"{gitignore_path}#{marker_id}",
                secret_backed=False,
                client="global",
                resolve_fn=make_resolve(),
            )
        ]
