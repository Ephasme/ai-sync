from __future__ import annotations

from dataclasses import dataclass

from ai_sync import mcp_sync


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
    calls: list[str]
    fail_mcp: bool = False
    instructions: list[str] | None = None

    def sync_mcp(self, servers: dict, secrets: dict, for_client) -> None:
        self.calls.append(f"sync_mcp:{self.name}")
        if self.fail_mcp:
            raise RuntimeError("boom")

    def sync_mcp_instructions(self, instructions: str) -> None:
        self.calls.append(f"sync_mcp_instructions:{self.name}")
        if self.instructions is not None:
            self.instructions.append(instructions)


def test_server_applies_to_client() -> None:
    display = FakeDisplay()
    assert not mcp_sync.server_applies_to_client({"enabled": False}, "codex", display)
    assert not mcp_sync.server_applies_to_client({"clients": "codex"}, "codex", display)
    assert mcp_sync.server_applies_to_client({"clients": ["codex"]}, "codex", display)
    assert any("clients' should be a list" in msg for _, msg in display.messages)


def test_sync_mcp_servers_skips_when_empty(monkeypatch) -> None:
    display = FakeDisplay()
    monkeypatch.setattr(mcp_sync, "CLIENTS", [])
    mcp_sync.sync_mcp_servers({}, display)
    assert any("MCP Servers: skipping" in msg for _, msg in display.messages)


def test_sync_mcp_servers_handles_errors_and_instructions(monkeypatch) -> None:
    display = FakeDisplay()
    calls: list[str] = []
    instructions: list[str] = []
    clients = [
        DummyClient("codex", calls, fail_mcp=True),
        DummyClient("cursor", calls, instructions=instructions),
    ]
    monkeypatch.setattr(mcp_sync, "CLIENTS", clients)
    manifest = {"servers": {"s1": {"method": "stdio", "command": "npx"}}, "global": {"instructions": "Use work MCP"}}
    mcp_sync.sync_mcp_servers(manifest, display)
    assert "sync_mcp:codex" in calls
    assert "sync_mcp:cursor" in calls
    assert "sync_mcp_instructions:cursor" in calls
    assert instructions == ["Use work MCP"]
    assert any("MCP sync failed" in msg for _, msg in display.messages)
