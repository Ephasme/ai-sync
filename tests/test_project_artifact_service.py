from __future__ import annotations

from pathlib import Path

from ai_sync.clients.base import Client
from ai_sync.data_classes.runtime_env import RuntimeEnv
from ai_sync.data_classes.write_spec import WriteSpec
from ai_sync.models import ProjectManifest
from ai_sync.services.project_artifact_service import ProjectArtifactService


class ProjectClient(Client):
    def __init__(self, client_name: str, project_root: Path) -> None:
        super().__init__(project_root)
        self._name = client_name

    @property
    def name(self) -> str:
        return self._name

    def build_agent_specs(
        self,
        alias: str,
        slug: str,
        meta: dict,
        raw_content: str,
        prompt_src_path: Path,
    ) -> list[WriteSpec]:
        return []

    def build_command_specs(
        self,
        alias: str,
        slug: str,
        meta: dict,
        raw_content: str,
        command_name: str,
    ) -> list[WriteSpec]:
        return []

    def build_mcp_specs(self, servers: dict, secrets: dict) -> list[WriteSpec]:
        return []

    def build_client_config_specs(self, settings: dict) -> list[WriteSpec]:
        return [
            WriteSpec(
                file_path=self.config_dir / "settings.json",
                format="json",
                target="/settings",
                value=settings,
            )
        ]

    def build_instructions_specs(self, instructions_content: str) -> list[WriteSpec]:
        return [
            WriteSpec(
                file_path=self.config_dir / "instructions.md",
                format="text",
                target="ai-sync:instructions",
                value=instructions_content,
            )
        ]


def test_project_artifact_service_collects_client_settings(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    client = ProjectClient("cursor", project_root)

    artifacts = ProjectArtifactService().collect_artifacts(
        project_root=project_root,
        manifest=ProjectManifest(sources={}, settings={"theme": "dark"}),
        resolved_sources={},
        runtime_env=RuntimeEnv(),
        mcp_manifest={},
        clients=[client],
    )

    settings_artifact = next(artifact for artifact in artifacts if artifact.kind == "client-settings")
    assert settings_artifact.client == "cursor"
    assert settings_artifact.plan_key == str(project_root / ".cursor" / "settings.json") + "#settings"
    specs = settings_artifact.resolve()
    assert specs == [
        WriteSpec(
            file_path=project_root / ".cursor" / "settings.json",
            format="json",
            target="/settings",
            value={"theme": "dark"},
        )
    ]


def test_project_artifact_service_collects_instructions_and_gitignore(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    (project_root / ".ai-sync").mkdir(parents=True)
    (project_root / ".ai-sync" / "instructions.md").write_text(
        "Follow project instructions.\n",
        encoding="utf-8",
    )
    client = ProjectClient("cursor", project_root)

    artifacts = ProjectArtifactService().collect_artifacts(
        project_root=project_root,
        manifest=ProjectManifest(sources={}),
        resolved_sources={},
        runtime_env=RuntimeEnv(),
        mcp_manifest={},
        clients=[client],
    )

    by_kind = {artifact.kind: artifact for artifact in artifacts}
    assert set(by_kind) == {"instructions", "git-safety"}

    instruction_specs = by_kind["instructions"].resolve()
    assert instruction_specs == [
        WriteSpec(
            file_path=project_root / ".cursor" / "instructions.md",
            format="text",
            target="ai-sync:instructions",
            value="Follow project instructions.\n",
        )
    ]

    gitignore_specs = by_kind["git-safety"].resolve()
    assert len(gitignore_specs) == 1
    assert gitignore_specs[0].file_path == project_root / ".gitignore"
    assert gitignore_specs[0].target == "ai-sync:gitignore"
    assert ".env.ai-sync" in str(gitignore_specs[0].value)
