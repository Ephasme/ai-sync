from __future__ import annotations

from pathlib import Path

from ai_sync import sync_runner
from ai_sync.clients.base import Client
from ai_sync.project import ProjectManifest, SourceConfig
from ai_sync.state_store import StateStore
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
    def __init__(self, client_name: str, project_root: Path, base: Path, calls: list[str]) -> None:
        super().__init__(project_root)
        self._name = client_name
        self._base = base
        self.calls = calls

    @property
    def name(self) -> str:
        return self._name

    @property
    def config_dir(self) -> Path:
        return self._base / f".{self._name}"

    def build_agent_specs(self, slug: str, meta: dict, raw_content: str, prompt_src_path: Path) -> list[WriteSpec]:
        return [
            WriteSpec(
                file_path=self.get_agents_dir() / slug / "prompt.md",
                format="text",
                target=f"ai-sync:agent:{slug}",
                value=raw_content,
            )
        ]

    def build_command_specs(self, slug: str, raw_content: str, command_src_path: Path) -> list[WriteSpec]:
        return [
            WriteSpec(
                file_path=self.config_dir / "commands" / command_src_path,
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

    def write_agent(self, slug: str, meta: dict, raw_content: str, prompt_src_path: Path, store: StateStore) -> None:
        self.calls.append(f"write_agent:{self._name}:{slug}")
        target = self.get_agents_dir() / slug / "prompt.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(raw_content, encoding="utf-8")

    def write_command(self, slug: str, raw_content: str, command_src_path: Path, store: StateStore) -> None:
        self.calls.append(f"write_command:{self._name}:{slug}")
        target = self.config_dir / "commands" / command_src_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(raw_content, encoding="utf-8")

    def sync_mcp(self, servers: dict, secrets: dict, store: StateStore) -> None:
        self.calls.append(f"sync_mcp:{self._name}:{len(servers)}")

    def sync_client_config(self, settings: dict, store: StateStore) -> None:
        self.calls.append(f"sync_client_config:{self._name}")


def _make_repo_root(tmp_path: Path) -> Path:
    """Create a single source root in the flat layout."""
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


def test_run_apply_syncs_agents_and_mcp(monkeypatch, tmp_path: Path) -> None:
    repo_root = _make_repo_root(tmp_path)
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / ".ai-sync.yaml").write_text("sources: {}\n", encoding="utf-8")
    display = FakeDisplay()
    calls: list[str] = []
    dummy_clients = [DummyClient("codex", project_root, tmp_path, calls)]
    monkeypatch.setattr(sync_runner, "create_clients", lambda pr: dummy_clients)

    manifest = ProjectManifest(
        sources={"company": SourceConfig(source=str(repo_root))},
        agents=["company/agent"],
        skills=["company/skill-one"],
        commands=[],
        mcp_servers=["company/srv"],
        settings={},
    )
    mcp_manifest = {"srv": {"method": "stdio", "command": "npx", "env": {"TOKEN": "abc"}}}
    secrets: dict = {}

    result = sync_runner.run_apply(
        project_root=project_root,
        source_roots={"company": repo_root},
        manifest=manifest,
        mcp_manifest=mcp_manifest,
        secrets=secrets,
        runtime_env={},
        display=display,
    )
    assert result == 0
    assert any("write_agent:codex:agent" in c for c in calls)
    assert any("sync_mcp:codex:1" in c for c in calls)


def test_sync_skills_copies_root_files(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    skill_root = repo_root / "skills" / "skill-one"
    skill_root.mkdir(parents=True)
    (skill_root / "SKILL.md").write_text("# Skill\n", encoding="utf-8")
    (skill_root / "reference.md").write_text("ref\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path))
    display = FakeDisplay()
    calls: list[str] = []
    project_root = tmp_path / "project"
    project_root.mkdir()
    client = DummyClient("codex", project_root, tmp_path, calls)
    store = StateStore(project_root)

    sync_runner.sync_skills({"company": repo_root}, ["company/skill-one"], [client], store, display)
    target = client.get_skills_dir() / "skill-one" / "reference.md"
    assert target.exists()


def test_sync_commands_copies_files(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    commands_root = repo_root / "commands"
    commands_root.mkdir(parents=True)
    (commands_root / "shortcut.md").write_text("Do a thing\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path))
    display = FakeDisplay()
    calls: list[str] = []
    project_root = tmp_path / "project"
    project_root.mkdir()
    client = DummyClient("codex", project_root, tmp_path, calls)
    store = StateStore(project_root)

    sync_runner.sync_commands({"company": repo_root}, ["company/shortcut.md"], [client], store, display)
    target = client.config_dir / "commands" / "shortcut.md"
    assert target.exists()
    assert "write_command:codex:company/shortcut.md" in calls


def test_sync_agents_uses_scoped_source_alias(tmp_path: Path, monkeypatch) -> None:
    repo_a = tmp_path / "repo-a"
    (repo_a / "prompts").mkdir(parents=True)
    (repo_a / "prompts" / "agent.md").write_text("## From A\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path))
    display = FakeDisplay()
    calls: list[str] = []
    project_root = tmp_path / "project"
    project_root.mkdir()
    client = DummyClient("codex", project_root, tmp_path, calls)
    store = StateStore(project_root)

    sync_runner.sync_agents({"company": repo_a}, ["company/agent"], [client], store, display)

    written = client.get_agents_dir() / "agent" / "prompt.md"
    assert written.read_text(encoding="utf-8") == "## From A\n"


def test_sync_rules_writes_generated_file_and_preserves_agents_md(tmp_path: Path, monkeypatch) -> None:
    repo_root = _make_repo_root(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    display = FakeDisplay()
    project_root = tmp_path / "project"
    project_root.mkdir()
    agents_md = project_root / "AGENTS.md"
    agents_md.write_text("# User Instructions\n\nKeep this file.\n", encoding="utf-8")
    store = StateStore(project_root)

    sync_runner.sync_rules(project_root, {"company": repo_root}, ["company/commit"], False, store, display)

    generated = project_root / "AGENTS.generated.md"
    assert generated.read_text(encoding="utf-8") == "Commit rules\n"

    agents_content = agents_md.read_text(encoding="utf-8")
    assert "# User Instructions" in agents_content
    assert "[`AGENTS.generated.md`](./AGENTS.generated.md)" in agents_content
    assert "Commit rules" not in agents_content


def test_sync_rules_empty_selection_removes_generated_file_but_keeps_agents_md(tmp_path: Path, monkeypatch) -> None:
    repo_root = _make_repo_root(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    display = FakeDisplay()
    project_root = tmp_path / "project"
    project_root.mkdir()
    agents_md = project_root / "AGENTS.md"
    agents_md.write_text("# User Instructions\n", encoding="utf-8")
    store = StateStore(project_root)

    sync_runner.sync_rules(project_root, {"company": repo_root}, ["company/commit"], False, store, display)
    sync_runner.sync_rules(project_root, {"company": repo_root}, [], False, store, display)

    assert not (project_root / "AGENTS.generated.md").exists()
    agents_content = agents_md.read_text(encoding="utf-8")
    assert agents_content == "# User Instructions\n"
    assert "AGENTS.generated.md" not in agents_content
