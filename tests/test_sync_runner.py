from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from ai_sync import sync_runner
from ai_sync.sync_runner import RunConfig, SyncOptions


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


@dataclass
class DummyClient:
    name: str
    base: Path
    calls: list[str]

    @property
    def config_dir(self) -> Path:
        return self.base / f".{self.name}"

    def get_agents_dir(self) -> Path:
        return self.config_dir / "agents"

    def get_skills_dir(self) -> Path:
        return self.config_dir / "skills"

    def write_agent(self, slug: str, meta: dict, raw_content: str, prompt_src_path: Path) -> None:
        self.calls.append(f"write_agent:{self.name}:{slug}")
        target = self.get_agents_dir() / slug / "prompt.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(raw_content, encoding="utf-8")

    def sync_mcp(self, servers: dict, secrets: dict, for_client) -> None:
        self.calls.append(f"sync_mcp:{self.name}:{len(servers)}")

    def sync_client_config(self, settings: dict) -> None:
        self.calls.append(f"sync_client_config:{self.name}")

    def enable_subagents_fallback(self) -> None:
        self.calls.append(f"enable_subagents_fallback:{self.name}")

    def sync_mcp_instructions(self, instructions: str) -> None:
        self.calls.append(f"sync_mcp_instructions:{self.name}")


def _make_config_root(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    (root / "config" / "prompts").mkdir(parents=True)
    (root / "config" / "skills" / "skill-one").mkdir(parents=True)
    (root / "config" / "mcp-servers").mkdir(parents=True)
    (root / "config" / "client-settings").mkdir(parents=True)
    (root / ".env.tpl").write_text("TOKEN=abc\n", encoding="utf-8")
    (root / "config" / "prompts" / "agent.md").write_text("## Task\nDo thing\n", encoding="utf-8")
    (root / "config" / "skills" / "skill-one" / "SKILL.md").write_text("# Skill\n", encoding="utf-8")
    (root / "config" / "mcp-servers" / "servers.yaml").write_text(
        "servers:\n  srv:\n    method: stdio\n    command: npx\n    env:\n      TOKEN: \"$TOKEN\"\n",
        encoding="utf-8",
    )
    (root / "config" / "client-settings" / "settings.yaml").write_text("mode: ask\n", encoding="utf-8")
    return root


def test_preflight_resolves_env_and_overrides(tmp_path: Path) -> None:
    root = _make_config_root(tmp_path)
    display = FakeDisplay()
    overrides = [("/servers/srv/command", "echo")]
    config = RunConfig(
        config_root=root,
        source_prompts=root / "config" / "prompts",
        source_skills=root / "config" / "skills",
        source_mcp=root / "config" / "mcp-servers",
        source_client_config=root / "config" / "client-settings",
        source_env_template=root / ".env.tpl",
        overrides=overrides,
        options=SyncOptions(agent_stems=frozenset({"agent"}), skill_names=frozenset({"skill-one"}), install_settings=True),
    )
    manifest = sync_runner.preflight(config, display)
    assert manifest["servers"]["srv"]["env"]["TOKEN"] == "abc"
    assert manifest["servers"]["srv"]["command"] == "echo"


def test_run_sync_warns_on_version_mismatch(monkeypatch, tmp_path: Path) -> None:
    root = _make_config_root(tmp_path)
    display = FakeDisplay()
    calls: list[str] = []
    monkeypatch.setattr(sync_runner, "CLIENTS", [DummyClient("codex", tmp_path, calls)])
    monkeypatch.setattr(sync_runner, "get_default_versions_path", lambda: tmp_path / "versions.json")
    monkeypatch.setattr(sync_runner, "check_client_versions", lambda _: (True, "Version mismatch: codex expected 1.2.x got 1.3.0"))
    result = sync_runner.run_sync(
        config_root=root,
        force=False,
        no_interactive=True,
        plain=True,
        overrides=[],
        display=display,
    )
    assert result == 0
    assert any("Warning: Version mismatch" in msg for _, msg in display.messages)
    assert any("write_agent:codex:agent" in c for c in calls)


def test_run_sync_force_writes_versions(monkeypatch, tmp_path: Path) -> None:
    root = _make_config_root(tmp_path)
    display = FakeDisplay()
    calls: list[str] = []
    versions_path = tmp_path / "versions.json"
    monkeypatch.setattr(sync_runner, "CLIENTS", [DummyClient("codex", tmp_path, calls)])
    monkeypatch.setattr(sync_runner, "get_default_versions_path", lambda: versions_path)
    monkeypatch.setattr(sync_runner, "detect_client_versions", lambda: {"codex": "1.2.3"})
    result = sync_runner.run_sync(
        config_root=root,
        force=True,
        no_interactive=True,
        plain=True,
        overrides=[],
        display=display,
    )
    assert result == 0
    assert versions_path.exists()


def test_preflight_missing_dirs_raises(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "config" / "mcp-servers").mkdir(parents=True)
    display = FakeDisplay()
    config = RunConfig(
        config_root=root,
        source_prompts=root / "config" / "prompts",
        source_skills=root / "config" / "skills",
        source_mcp=root / "config" / "mcp-servers",
        source_client_config=root / "config" / "client-settings",
        source_env_template=root / ".env.tpl",
        overrides=[],
        options=SyncOptions(agent_stems=frozenset(), skill_names=frozenset(), install_settings=True),
    )
    with pytest.raises(RuntimeError):
        sync_runner.preflight(config, display)
