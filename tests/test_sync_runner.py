from __future__ import annotations

from pathlib import Path
from typing import cast

from ai_sync.clients.base import Client
from ai_sync.data_classes.prepared_artifacts import PreparedArtifacts
from ai_sync.data_classes.prepared_mcp_server import PreparedMcpServer
from ai_sync.data_classes.resolved_artifact_set import ResolvedArtifactSet
from ai_sync.data_classes.resolved_source import ResolvedSource
from ai_sync.data_classes.runtime_env import RuntimeEnv
from ai_sync.data_classes.write_spec import WriteSpec
from ai_sync.di import create_container
from ai_sync.models import ProjectManifest, SourceConfig
from ai_sync.services.agent_artifact_service import AgentArtifactService
from ai_sync.services.artifact_bundle_service import ArtifactBundleService
from ai_sync.services.command_artifact_service import CommandArtifactService
from ai_sync.services.skill_artifact_service import SkillArtifactService


class FakeDisplay:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def rule(self, title: str, style: str = "section") -> None:
        self.messages.append((style, title))

    def print(self, msg: str, style: str = "normal") -> None:
        self.messages.append((style, msg))

    def panel(self, content: str, *, title: str = "", style: str = "normal") -> None:
        self.messages.append((style, f"{title}:{content}"))

    def table(self, headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> None:
        self.messages.append(("table", ",".join(headers)))


class DummyClient(Client):
    def __init__(self, client_name: str, project_root: Path, calls: list[str]) -> None:
        super().__init__(project_root)
        self._name = client_name
        self.calls = calls

    @property
    def name(self) -> str:
        return self._name

    def build_agent_specs(
        self, alias: str, slug: str, meta: dict, raw_content: str, prompt_src_path: Path
    ) -> list[WriteSpec]:
        prefixed_slug = f"{alias}-{slug}"
        return [
            WriteSpec(
                file_path=self.get_agents_dir() / prefixed_slug / "prompt.md",
                format="text",
                target=f"ai-sync:agent:{prefixed_slug}",
                value=raw_content,
            )
        ]

    def build_command_specs(
        self, alias: str, slug: str, meta: dict, raw_content: str, command_name: str
    ) -> list[WriteSpec]:
        rel = Path(command_name)
        prefixed = rel.with_name(f"{alias}-{rel.name}.md")
        return [
            WriteSpec(
                file_path=self.config_dir / "commands" / prefixed,
                format="text",
                target=f"ai-sync:command:{slug}",
                value=raw_content,
            )
        ]

    def build_mcp_specs(self, servers: dict, secrets: dict) -> list[WriteSpec]:
        return [
            WriteSpec(
                file_path=self.config_dir / "config.toml",
                format="toml",
                target=f"/mcp_servers/{sid}",
                value=server,
            )
            for sid, server in servers.items()
        ]

    def build_client_config_specs(self, settings: dict) -> list[WriteSpec]:
        return []


def _resolved(alias: str, root: Path) -> ResolvedSource:
    return ResolvedSource(
        alias=alias, source=str(root), kind="local",
        root=root, fingerprint="test", version=None,
    )


def _make_repo_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "agents" / "agent").mkdir(parents=True)
    (root / "skills" / "skill-one" / "files").mkdir(parents=True)
    (root / "commands" / "shortcut").mkdir(parents=True)
    (root / "rules" / "commit").mkdir(parents=True)
    (root / "agents" / "agent" / "artifact.yaml").write_text(
        "slug: agent\n"
        "name: Agent\n"
        "description: General agent assistant\n",
        encoding="utf-8",
    )
    (root / "agents" / "agent" / "prompt.md").write_text("## Task\nDo thing\n", encoding="utf-8")
    (root / "skills" / "skill-one" / "artifact.yaml").write_text(
        "name: skill-one\n"
        "description: Example skill\n"
        "disable-model-invocation: true\n",
        encoding="utf-8",
    )
    (root / "skills" / "skill-one" / "prompt.md").write_text("# Skill\n", encoding="utf-8")
    (root / "skills" / "skill-one" / "files" / "reference.md").write_text("ref\n", encoding="utf-8")
    (root / "commands" / "shortcut" / "artifact.yaml").write_text(
        "name: Shortcut\n"
        "description: A shortcut command\n",
        encoding="utf-8",
    )
    (root / "commands" / "shortcut" / "prompt.md").write_text("Do a thing\n", encoding="utf-8")
    (root / "rules" / "commit" / "artifact.yaml").write_text(
        "name: Commit conventions\n"
        "description: Commit conventions\n"
        "alwaysApply: true\n",
        encoding="utf-8",
    )
    (root / "rules" / "commit" / "prompt.md").write_text("Commit rules\n", encoding="utf-8")
    (root / "mcp_servers" / "srv").mkdir(parents=True)
    (root / "mcp_servers" / "srv" / "artifact.yaml").write_text(
        "name: Example MCP\n"
        "description: Example MCP server for test coverage.\n"
        "method: stdio\n"
        "command: npx\n"
        "dependencies:\n"
        "  env:\n"
        "    TOKEN: abc\n",
        encoding="utf-8",
    )
    return root


def _run_apply(*, project_root: Path, resolved_artifacts, display) -> int:
    container = create_container()
    return container.apply_service().run_apply(
        project_root=project_root,
        resolved_artifacts=resolved_artifacts,
        display=display,
    )


def _resolve_artifacts(
    *,
    project_root: Path,
    manifest: ProjectManifest,
    resolved_sources: dict[str, ResolvedSource],
    runtime_env: RuntimeEnv,
    prepared_artifacts: PreparedArtifacts,
    clients,
):
    artifacts = create_container().artifact_service().collect_artifacts(
        project_root=project_root,
        manifest=manifest,
        resolved_sources=resolved_sources,
        runtime_env=runtime_env,
        prepared_artifacts=prepared_artifacts,
        clients=clients,
    )
    entries = []
    desired_targets: set[tuple[str, str, str]] = set()
    for artifact in artifacts:
        specs = artifact.resolve()
        entries.append((artifact, specs))
        for spec in specs:
            if isinstance(spec, WriteSpec):
                desired_targets.add((str(spec.file_path), spec.format, spec.target))
    return ResolvedArtifactSet(entries=entries, desired_targets=desired_targets)


# ---------------------------------------------------------------------------
# run_apply integration tests
# ---------------------------------------------------------------------------


def test_run_apply_syncs_agents_and_mcp(tmp_path: Path) -> None:
    repo_root = _make_repo_root(tmp_path)
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / ".ai-sync.yaml").write_text("sources: {}\n", encoding="utf-8")

    display = FakeDisplay()
    dummy_clients = [DummyClient("codex", project_root, [])]

    resolved_sources = {"company": _resolved("company", repo_root)}
    manifest = ProjectManifest(
        sources={"company": SourceConfig(source=str(repo_root))},
        agents=["company/agent"],
        skills=["company/skill-one"],
        commands=[],
        mcp_servers=["company/srv"],
        settings={},
    )
    prepared = PreparedArtifacts(
        mcp_servers=[
            PreparedMcpServer(
                scoped_ref="company/srv",
                source_alias="company",
                server_id="srv",
                source_config={},
                runtime_config={
                    "method": "stdio",
                    "command": "npx",
                    "name": "Example MCP",
                    "description": "Example MCP server for test coverage.",
                    "env": {"TOKEN": "abc"},
                },
            )
        ]
    )

    resolved = _resolve_artifacts(
        project_root=project_root,
        manifest=manifest,
        resolved_sources=resolved_sources,
        runtime_env=RuntimeEnv(),
        prepared_artifacts=prepared,
        clients=dummy_clients,
    )
    result = _run_apply(project_root=project_root, resolved_artifacts=resolved, display=display)
    assert result == 0

    agent_prompt = project_root / ".codex" / "agents" / "company-agent" / "prompt.md"
    assert agent_prompt.exists()
    assert "Do thing" in agent_prompt.read_text(encoding="utf-8")

    mcp_config = project_root / ".codex" / "config.toml"
    assert mcp_config.exists()


def test_run_apply_writes_rules_and_index(tmp_path: Path) -> None:
    repo_root = _make_repo_root(tmp_path)
    project_root = tmp_path / "project"
    project_root.mkdir()
    agents_md = project_root / "AGENTS.md"
    agents_md.write_text("# User Instructions\n\nKeep this file.\n", encoding="utf-8")

    display = FakeDisplay()
    dummy_clients = [DummyClient("codex", project_root, [])]

    resolved_sources = {"company": _resolved("company", repo_root)}
    manifest = ProjectManifest(
        sources={"company": SourceConfig(source=str(repo_root))},
        rules=["company/commit"],
    )

    resolved = _resolve_artifacts(
        project_root=project_root,
        manifest=manifest,
        resolved_sources=resolved_sources,
        runtime_env=RuntimeEnv(),
        prepared_artifacts=PreparedArtifacts(),
        clients=dummy_clients,
    )
    result = _run_apply(project_root=project_root, resolved_artifacts=resolved, display=display)
    assert result == 0

    rule_file = project_root / ".ai-sync" / "rules" / "company-commit.md"
    assert rule_file.exists()
    assert "Commit rules" in rule_file.read_text(encoding="utf-8")

    agents_content = agents_md.read_text(encoding="utf-8")
    assert "# User Instructions" in agents_content
    assert ".ai-sync/rules/" in agents_content


def test_run_apply_removes_stale_rules(tmp_path: Path) -> None:
    repo_root = _make_repo_root(tmp_path)
    project_root = tmp_path / "project"
    project_root.mkdir()
    agents_md = project_root / "AGENTS.md"
    agents_md.write_text("# User Instructions\n", encoding="utf-8")

    display = FakeDisplay()
    dummy_clients = [DummyClient("codex", project_root, [])]

    resolved_sources = {"company": _resolved("company", repo_root)}

    manifest_with = ProjectManifest(
        sources={"company": SourceConfig(source=str(repo_root))},
        rules=["company/commit"],
    )
    resolved_with = _resolve_artifacts(
        project_root=project_root,
        manifest=manifest_with,
        resolved_sources=resolved_sources,
        runtime_env=RuntimeEnv(),
        prepared_artifacts=PreparedArtifacts(),
        clients=dummy_clients,
    )
    _run_apply(project_root=project_root, resolved_artifacts=resolved_with, display=display)

    manifest_empty = ProjectManifest(
        sources={"company": SourceConfig(source=str(repo_root))},
    )
    resolved_empty = _resolve_artifacts(
        project_root=project_root,
        manifest=manifest_empty,
        resolved_sources=resolved_sources,
        runtime_env=RuntimeEnv(),
        prepared_artifacts=PreparedArtifacts(),
        clients=dummy_clients,
    )
    _run_apply(project_root=project_root, resolved_artifacts=resolved_empty, display=display)

    rule_file = project_root / ".ai-sync" / "rules" / "company-commit.md"
    assert not rule_file.exists()

    agents_content = agents_md.read_text(encoding="utf-8")
    assert "# User Instructions" in agents_content
    assert ".ai-sync/rules/" not in agents_content


# ---------------------------------------------------------------------------
# Artifact factory unit tests
# ---------------------------------------------------------------------------


def test_skill_artifacts_include_all_files(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    skill_root = repo_root / "skills" / "skill-one"
    (skill_root / "files").mkdir(parents=True)
    (skill_root / "artifact.yaml").write_text(
        "name: skill-one\n"
        "description: Example skill\n"
        "disable-model-invocation: true\n",
        encoding="utf-8",
    )
    (skill_root / "prompt.md").write_text("# Skill\n", encoding="utf-8")
    (skill_root / "files" / "reference.md").write_text("ref\n", encoding="utf-8")

    project_root = tmp_path / "project"
    project_root.mkdir()
    client = DummyClient("codex", project_root, [])
    resolved_sources = {"company": _resolved("company", repo_root)}

    manifest = ProjectManifest(
        sources={"company": SourceConfig(source=str(repo_root))},
        skills=["company/skill-one"],
    )

    artifacts = SkillArtifactService(
        artifact_bundle_service=ArtifactBundleService()
    ).collect_artifacts(
        project_root=project_root,
        manifest=manifest,
        resolved_sources=resolved_sources,
        runtime_env=RuntimeEnv(),
        prepared_artifacts=PreparedArtifacts(),
        clients=[client],
    )
    assert len(artifacts) == 1
    assert artifacts[0].name == "skill-one"
    assert artifacts[0].description == "Example skill"

    specs = artifacts[0].resolve()
    write_specs = [s for s in specs if isinstance(s, WriteSpec)]
    rel_paths = {
        s.file_path.relative_to(project_root / ".codex" / "skills" / "company-skill-one").as_posix()
        for s in write_specs
    }
    assert "SKILL.md" in rel_paths
    assert "reference.md" in rel_paths
    assert "files/reference.md" not in rel_paths

    skill_spec = next(spec for spec in write_specs if spec.file_path.name == "SKILL.md")
    skill_value = cast(str, skill_spec.value)
    assert skill_value.startswith(
        "---\n"
        "name: skill-one\n"
        "description: Example skill\n"
        "disable-model-invocation: true\n"
        "---\n\n"
    )
    assert skill_value.endswith("# Skill\n")


def test_command_artifacts_produce_write_specs(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / "commands" / "review" / "shortcut").mkdir(parents=True)
    (repo_root / "commands" / "review" / "shortcut" / "artifact.yaml").write_text(
        "name: Shortcut\n"
        "description: A shortcut command\n",
        encoding="utf-8",
    )
    (repo_root / "commands" / "review" / "shortcut" / "prompt.md").write_text("Do a thing\n", encoding="utf-8")

    project_root = tmp_path / "project"
    project_root.mkdir()
    client = DummyClient("codex", project_root, [])
    resolved_sources = {"company": _resolved("company", repo_root)}

    manifest = ProjectManifest(
        sources={"company": SourceConfig(source=str(repo_root))},
        commands=["company/review/shortcut"],
    )

    artifacts = CommandArtifactService(
        artifact_bundle_service=ArtifactBundleService()
    ).collect_artifacts(
        project_root=project_root,
        manifest=manifest,
        resolved_sources=resolved_sources,
        runtime_env=RuntimeEnv(),
        prepared_artifacts=PreparedArtifacts(),
        clients=[client],
    )
    assert len(artifacts) == 1
    assert artifacts[0].kind == "command"
    assert artifacts[0].name == "Shortcut"
    assert artifacts[0].description == "A shortcut command"

    specs = artifacts[0].resolve()
    assert len(specs) == 1
    assert isinstance(specs[0], WriteSpec)
    assert specs[0].value == "Do a thing\n"
    assert "review/company-shortcut.md" in str(specs[0].file_path)


def test_agent_artifacts_use_scoped_alias(tmp_path: Path) -> None:
    repo_a = tmp_path / "repo-a"
    (repo_a / "agents" / "agent").mkdir(parents=True)
    (repo_a / "agents" / "agent" / "artifact.yaml").write_text(
        "slug: agent\n"
        "name: Agent\n"
        "description: Agent from repo A\n",
        encoding="utf-8",
    )
    (repo_a / "agents" / "agent" / "prompt.md").write_text("## From A\n", encoding="utf-8")

    project_root = tmp_path / "project"
    project_root.mkdir()
    client = DummyClient("codex", project_root, [])
    resolved_sources = {"company": _resolved("company", repo_a)}

    manifest = ProjectManifest(
        sources={"company": SourceConfig(source=str(repo_a))},
        agents=["company/agent"],
    )

    artifacts = AgentArtifactService(
        artifact_bundle_service=ArtifactBundleService()
    ).collect_artifacts(
        project_root=project_root,
        manifest=manifest,
        resolved_sources=resolved_sources,
        runtime_env=RuntimeEnv(),
        prepared_artifacts=PreparedArtifacts(),
        clients=[client],
    )
    assert len(artifacts) == 1
    assert artifacts[0].name == "Agent"
    assert artifacts[0].description == "Agent from repo A"

    specs = artifacts[0].resolve()
    assert isinstance(specs[0], WriteSpec)
    assert specs[0].value == "## From A\n"
    assert "company-agent" in str(specs[0].file_path)
