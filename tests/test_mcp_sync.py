from __future__ import annotations

from pathlib import Path

from ai_sync import mcp_sync
from ai_sync.clients.base import Client
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
    def __init__(self, client_name: str, project_root: Path, calls: list[str], *, fail_mcp: bool = False) -> None:
        super().__init__(project_root)
        self._name = client_name
        self.calls = calls
        self.fail_mcp = fail_mcp

    @property
    def name(self) -> str:
        return self._name

    def write_agent(self, slug: str, meta: dict, raw_content: str, prompt_src_path: Path, store: StateStore) -> None:
        pass

    def write_command(self, slug: str, raw_content: str, command_src_path: Path, store: StateStore) -> None:
        pass

    def sync_mcp(self, servers: dict, secrets: dict, store: StateStore) -> None:
        self.calls.append(f"sync_mcp:{self._name}")
        if self.fail_mcp:
            raise RuntimeError("boom")

    def sync_client_config(self, settings: dict, store: StateStore) -> None:
        pass


def test_sync_mcp_servers_skips_when_empty() -> None:
    display = FakeDisplay()
    mcp_sync.sync_mcp_servers({}, [], {}, StateStore(Path("/tmp")), display)
    assert any("MCP Servers: skipping" in msg for _, msg in display.messages)


def test_sync_mcp_servers_handles_errors() -> None:
    display = FakeDisplay()
    calls: list[str] = []
    project_root = Path("/tmp/project")
    clients = [
        DummyClient("codex", project_root, calls, fail_mcp=True),
        DummyClient("cursor", project_root, calls),
    ]
    store = StateStore(project_root)
    servers = {"s1": {"method": "stdio", "command": "npx"}}
    secrets: dict = {}
    mcp_sync.sync_mcp_servers(servers, clients, secrets, store, display)
    assert "sync_mcp:codex" in calls
    assert "sync_mcp:cursor" in calls
    assert any("MCP sync failed" in msg for _, msg in display.messages)
