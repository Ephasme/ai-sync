from __future__ import annotations

from pathlib import Path

from ai_sync import sync_runner
from ai_sync.artifacts import _agent_artifacts, _command_artifacts, _skill_artifacts
from ai_sync.clients.base import Client
from ai_sync.project import ProjectManifest, SourceConfig
from ai_sync.source_resolver import ResolvedSource
from ai_sync.track_write import WriteSpec


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
        self, alias: str, slug: str, raw_content: str, command_src_path: Path
    ) -> list[WriteSpec]:
        prefixed = command_src_path.with_name(f"{alias}-{command_src_path.name}")
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
    (root / "prompts").mkdir(parents=True)
    (root / "skills" / "skill-one").mkdir(parents=True)
    (root / "commands").mkdir(parents=True)
    (root / "rules").mkdir(parents=True)
    (root / ".env.ai-sync.tpl").write_text("TOKEN=abc\n", encoding="utf-8")
    (root / "prompts" / "agent.md").write_text("## Task\nDo thing\n", encoding="utf-8")
    (root / "skills" / "skill-one" / "SKILL.md").write_text("# Skill\n", encoding="utf-8")
    (root / "commands" / "shortcut.md").write_text("Do a thing\n", encoding="utf-8")
    (root / "rules" / "commit.md").write_text("Commit rules\n", encoding="utf-8")
    (root / "mcp-servers" / "srv").mkdir(parents=True)
    (root / "mcp-servers" / "srv" / "server.yaml").write_text(
        'method: stdio\ncommand: npx\nenv:\n  TOKEN: "$TOKEN"\n',
        encoding="utf-8",
    )
    return root


# ---------------------------------------------------------------------------
# run_apply integration tests
# ---------------------------------------------------------------------------


def test_run_apply_syncs_agents_and_mcp(monkeypatch, tmp_path: Path) -> None:
    repo_root = _make_repo_root(tmp_path)
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / ".ai-sync.yaml").write_text("sources: {}\n", encoding="utf-8")

    display = FakeDisplay()
    calls: list[str] = []
    dummy_clients = [DummyClient("codex", project_root, calls)]
    monkeypatch.setattr(sync_runner, "create_clients", lambda pr: dummy_clients)

    resolved_sources = {"company": _resolved("company", repo_root)}
    manifest = ProjectManifest(
        sources={"company": SourceConfig(source=str(repo_root))},
        agents=["company/agent"],
        skills=["company/skill-one"],
        commands=[],
        mcp_servers=["company/srv"],
        settings={},
    )
    mcp_manifest = {"srv": {"method": "stdio", "command": "npx", "env": {"TOKEN": "abc"}}}

    result = sync_runner.run_apply(
        project_root=project_root,
        source_roots={"company": repo_root},
        manifest=manifest,
        mcp_manifest=mcp_manifest,
        secrets={},
        runtime_env={},
        resolved_sources=resolved_sources,
        display=display,
    )
    assert result == 0

    agent_prompt = project_root / ".codex" / "agents" / "company-agent" / "prompt.md"
    assert agent_prompt.exists()
    assert "Do thing" in agent_prompt.read_text(encoding="utf-8")

    mcp_config = project_root / ".codex" / "config.toml"
    assert mcp_config.exists()


def test_run_apply_writes_rules_and_index(monkeypatch, tmp_path: Path) -> None:
    repo_root = _make_repo_root(tmp_path)
    project_root = tmp_path / "project"
    project_root.mkdir()
    agents_md = project_root / "AGENTS.md"
    agents_md.write_text("# User Instructions\n\nKeep this file.\n", encoding="utf-8")

    display = FakeDisplay()
    dummy_clients = [DummyClient("codex", project_root, [])]
    monkeypatch.setattr(sync_runner, "create_clients", lambda pr: dummy_clients)

    resolved_sources = {"company": _resolved("company", repo_root)}
    manifest = ProjectManifest(
        sources={"company": SourceConfig(source=str(repo_root))},
        rules=["company/commit"],
    )

    result = sync_runner.run_apply(
        project_root=project_root,
        source_roots={"company": repo_root},
        manifest=manifest,
        mcp_manifest={},
        secrets={},
        runtime_env={},
        resolved_sources=resolved_sources,
        display=display,
    )
    assert result == 0

    rule_file = project_root / ".ai-sync" / "rules" / "company-commit.md"
    assert rule_file.exists()
    assert "Commit rules" in rule_file.read_text(encoding="utf-8")

    agents_content = agents_md.read_text(encoding="utf-8")
    assert "# User Instructions" in agents_content
    assert "company-commit" in agents_content


def test_run_apply_removes_stale_rules(monkeypatch, tmp_path: Path) -> None:
    repo_root = _make_repo_root(tmp_path)
    project_root = tmp_path / "project"
    project_root.mkdir()
    agents_md = project_root / "AGENTS.md"
    agents_md.write_text("# User Instructions\n", encoding="utf-8")

    display = FakeDisplay()
    dummy_clients = [DummyClient("codex", project_root, [])]
    monkeypatch.setattr(sync_runner, "create_clients", lambda pr: dummy_clients)

    resolved_sources = {"company": _resolved("company", repo_root)}

    manifest_with = ProjectManifest(
        sources={"company": SourceConfig(source=str(repo_root))},
        rules=["company/commit"],
    )
    sync_runner.run_apply(
        project_root=project_root,
        source_roots={"company": repo_root},
        manifest=manifest_with,
        mcp_manifest={},
        secrets={},
        runtime_env={},
        resolved_sources=resolved_sources,
        display=display,
    )

    manifest_empty = ProjectManifest(
        sources={"company": SourceConfig(source=str(repo_root))},
    )
    sync_runner.run_apply(
        project_root=project_root,
        source_roots={"company": repo_root},
        manifest=manifest_empty,
        mcp_manifest={},
        secrets={},
        runtime_env={},
        resolved_sources=resolved_sources,
        display=display,
    )

    rule_file = project_root / ".ai-sync" / "rules" / "company-commit.md"
    assert not rule_file.exists()

    agents_content = agents_md.read_text(encoding="utf-8")
    assert "# User Instructions" in agents_content
    assert "company-commit" not in agents_content


# ---------------------------------------------------------------------------
# Artifact factory unit tests
# ---------------------------------------------------------------------------


def test_skill_artifacts_include_all_files(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    skill_root = repo_root / "skills" / "skill-one"
    skill_root.mkdir(parents=True)
    (skill_root / "SKILL.md").write_text("# Skill\n", encoding="utf-8")
    (skill_root / "reference.md").write_text("ref\n", encoding="utf-8")

    project_root = tmp_path / "project"
    project_root.mkdir()
    client = DummyClient("codex", project_root, [])
    resolved_sources = {"company": _resolved("company", repo_root)}

    manifest = ProjectManifest(
        sources={"company": SourceConfig(source=str(repo_root))},
        skills=["company/skill-one"],
    )

    artifacts = _skill_artifacts(manifest, resolved_sources, [client])
    assert len(artifacts) == 1

    specs = artifacts[0].resolve()
    names = {s.file_path.name for s in specs}
    assert "SKILL.md" in names
    assert "reference.md" in names


def test_command_artifacts_produce_write_specs(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / "commands").mkdir(parents=True)
    (repo_root / "commands" / "shortcut.md").write_text("Do a thing\n", encoding="utf-8")

    project_root = tmp_path / "project"
    project_root.mkdir()
    client = DummyClient("codex", project_root, [])
    resolved_sources = {"company": _resolved("company", repo_root)}

    manifest = ProjectManifest(
        sources={"company": SourceConfig(source=str(repo_root))},
        commands=["company/shortcut.md"],
    )

    artifacts = _command_artifacts(manifest, resolved_sources, [client])
    assert len(artifacts) == 1
    assert artifacts[0].kind == "command"

    specs = artifacts[0].resolve()
    assert len(specs) == 1
    assert specs[0].value == "Do a thing\n"
    assert "company-shortcut.md" in str(specs[0].file_path)


def test_agent_artifacts_use_scoped_alias(tmp_path: Path) -> None:
    repo_a = tmp_path / "repo-a"
    (repo_a / "prompts").mkdir(parents=True)
    (repo_a / "prompts" / "agent.md").write_text("## From A\n", encoding="utf-8")

    project_root = tmp_path / "project"
    project_root.mkdir()
    client = DummyClient("codex", project_root, [])
    display = FakeDisplay()
    resolved_sources = {"company": _resolved("company", repo_a)}

    manifest = ProjectManifest(
        sources={"company": SourceConfig(source=str(repo_a))},
        agents=["company/agent"],
    )

    artifacts = _agent_artifacts(manifest, resolved_sources, [client], display)
    assert len(artifacts) == 1

    specs = artifacts[0].resolve()
    assert specs[0].value == "## From A\n"
    assert "company-agent" in str(specs[0].file_path)
