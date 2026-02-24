from __future__ import annotations

from pathlib import Path

from ai_sync import sync_runner
from ai_sync.clients.base import Client
from ai_sync.project import ProjectManifest
from ai_sync.state_store import StateStore


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

    def write_agent(
        self, slug: str, meta: dict, raw_content: str, prompt_src_path: Path, store: StateStore
    ) -> None:
        self.calls.append(f"write_agent:{self._name}:{slug}")
        target = self.get_agents_dir() / slug / "prompt.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(raw_content, encoding="utf-8")

    def write_command(
        self, slug: str, raw_content: str, command_src_path: Path, store: StateStore
    ) -> None:
        self.calls.append(f"write_command:{self._name}:{slug}")
        target = self.config_dir / "commands" / command_src_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(raw_content, encoding="utf-8")

    def sync_mcp(self, servers: dict, secrets: dict, store: StateStore) -> None:
        self.calls.append(f"sync_mcp:{self._name}:{len(servers)}")

    def sync_client_config(self, settings: dict, store: StateStore) -> None:
        self.calls.append(f"sync_client_config:{self._name}")


def _make_config_root(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    (root / "config" / "prompts").mkdir(parents=True)
    (root / "config" / "skills" / "skill-one").mkdir(parents=True)
    (root / "config" / "commands").mkdir(parents=True)
    (root / ".env.tpl").write_text("TOKEN=abc\n", encoding="utf-8")
    (root / "config" / "prompts" / "agent.md").write_text("## Task\nDo thing\n", encoding="utf-8")
    (root / "config" / "skills" / "skill-one" / "SKILL.md").write_text("# Skill\n", encoding="utf-8")
    (root / "config" / "commands" / "shortcut.md").write_text("Do a thing\n", encoding="utf-8")
    (root / "config" / "mcp-servers.yaml").write_text(
        "servers:\n  srv:\n    method: stdio\n    command: npx\n    env:\n      TOKEN: \"$TOKEN\"\n",
        encoding="utf-8",
    )
    return root


def test_run_apply_syncs_agents_and_mcp(monkeypatch, tmp_path: Path) -> None:
    root = _make_config_root(tmp_path)
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / ".ai-sync.yaml").write_text("agents: [agent]\nskills: [skill-one]\n", encoding="utf-8")
    display = FakeDisplay()
    calls: list[str] = []
    dummy_clients = [DummyClient("codex", project_root, tmp_path, calls)]
    monkeypatch.setattr(sync_runner, "create_clients", lambda pr: dummy_clients)

    manifest = ProjectManifest(agents=["agent"], skills=["skill-one"], commands=[], mcp_servers=["srv"], settings={})
    mcp_manifest = {"srv": {"method": "stdio", "command": "npx", "env": {"TOKEN": "abc"}}}
    secrets: dict = {}

    result = sync_runner.run_apply(
        project_root=project_root,
        config_root=root,
        manifest=manifest,
        mcp_manifest=mcp_manifest,
        secrets=secrets,
        display=display,
    )
    assert result == 0
    assert any("write_agent:codex:agent" in c for c in calls)
    assert any("sync_mcp:codex:1" in c for c in calls)


def test_sync_skills_copies_root_files(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "root"
    skill_root = root / "config" / "skills" / "skill-one"
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

    sync_runner.sync_skills(root, ["skill-one"], [client], store, display)
    target = client.get_skills_dir() / "skill-one" / "reference.md"
    assert target.exists()


def test_sync_commands_copies_files(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "root"
    commands_root = root / "config" / "commands"
    commands_root.mkdir(parents=True)
    (commands_root / "shortcut.md").write_text("Do a thing\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path))
    display = FakeDisplay()
    calls: list[str] = []
    project_root = tmp_path / "project"
    project_root.mkdir()
    client = DummyClient("codex", project_root, tmp_path, calls)
    store = StateStore(project_root)

    sync_runner.sync_commands(root, ["shortcut.md"], [client], store, display)
    target = client.config_dir / "commands" / "shortcut.md"
    assert target.exists()
    assert "write_command:codex:shortcut.md" in calls
