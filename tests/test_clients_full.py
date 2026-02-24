from __future__ import annotations

import json
from pathlib import Path

import pytest
import tomli as tomllib

from ai_sync.clients.codex import CodexClient
from ai_sync.clients.cursor import CursorClient
from ai_sync.clients.gemini import GeminiClient
from ai_sync.state_store import StateStore


# ---------------------------------------------------------------------------
# sync_mcp + sync_client_config (integration)
# ---------------------------------------------------------------------------


def test_codex_sync_mcp_and_config(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    client = CodexClient(tmp_path)
    servers = {
        "s1": {
            "method": "stdio",
            "command": "npx",
            "args": ["x"],
            "env": {"TOKEN": "secret"},
            "bearer_token_env_var": "TOKEN",
        }
    }
    client.sync_mcp(servers, {"servers": {}}, store)
    config_path = tmp_path / ".codex" / "config.toml"
    assert config_path.exists()
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert "mcp_servers" in data
    mcp_env = tmp_path / ".codex" / "mcp.env"
    assert mcp_env.exists()
    assert "export TOKEN=" in mcp_env.read_text(encoding="utf-8")

    client.sync_client_config({"mode": "yolo", "subagents": True}, store)
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert data["approval_policy"] == "never"
    assert data["sandbox_mode"] == "danger-full-access"


def test_cursor_sync_mcp_and_config(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    client = CursorClient(tmp_path)
    servers = {
        "s1": {
            "method": "http",
            "url": "https://x",
            "trust": True,
            "auth": {"token": "public"},
            "env": {"A": "B"},
            "timeout_seconds": 1,
        }
    }
    secrets = {"servers": {"s1": {"auth": {"token": "secret"}}}}
    client.sync_mcp(servers, secrets, store)
    mcp_path = tmp_path / ".cursor" / "mcp.json"
    data = json.loads(mcp_path.read_text(encoding="utf-8"))
    assert data["mcpServers"]["s1"]["url"] == "https://x"
    assert data["mcpServers"]["s1"]["auth"]["token"] == "secret"
    client.sync_client_config({"mode": "yolo"}, store)
    cfg = json.loads((tmp_path / ".cursor" / "cli-config.json").read_text(encoding="utf-8"))
    assert "Shell(*)" in cfg["permissions"]["allow"]


def test_gemini_sync_mcp(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    client = GeminiClient(tmp_path)
    servers = {
        "s1": {
            "method": "http",
            "httpUrl": "https://x",
            "oauth": {"enabled": True, "scopes": ["a"]},
        }
    }
    secrets = {"servers": {"s1": {"oauth": {"clientId": "id", "clientSecret": "secret"}}}}
    client.sync_mcp(servers, secrets, store)
    settings_path = tmp_path / ".gemini" / "settings.json"
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    assert data["mcpServers"]["s1"]["oauth"]["clientId"] == "id"


# ---------------------------------------------------------------------------
# write_agent
# ---------------------------------------------------------------------------


def test_codex_write_agent(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    client = CodexClient(tmp_path)
    meta = {"reasoning_effort": "medium", "web_search": False}
    client.write_agent("my-agent", meta, "Do the thing", Path("agent.md"), store)
    agent_dir = tmp_path / ".codex" / "agents" / "my-agent"
    prompt = agent_dir / "prompt.md"
    assert prompt.exists()
    assert "Do the thing" in prompt.read_text(encoding="utf-8")
    config = tomllib.loads((agent_dir / "config.toml").read_text(encoding="utf-8"))
    assert config["model"] == "auto"
    assert config["model_reasoning_effort"] == "medium"
    assert config["web_search"] == "off"


def test_cursor_write_agent(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    client = CursorClient(tmp_path)
    meta = {"name": "my-agent", "description": "A test agent", "is_background": True}
    client.write_agent("my-agent", meta, "Task content", Path("agent.md"), store)
    agent_path = tmp_path / ".cursor" / "agents" / "my-agent.md"
    assert agent_path.exists()
    content = agent_path.read_text(encoding="utf-8")
    assert "Task content" in content
    assert "is_background: true" in content
    assert '"A test agent"' in content


def test_gemini_write_agent(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    client = GeminiClient(tmp_path)
    meta = {"description": "Test desc", "tools": ["search", "browse"]}
    client.write_agent("my-agent", meta, "Prompt body", Path("agent.md"), store)
    agent_path = tmp_path / ".gemini" / "agents" / "my-agent.md"
    assert agent_path.exists()
    content = agent_path.read_text(encoding="utf-8")
    assert "Prompt body" in content
    assert "my-agent" in content
    assert '["search", "browse"]' in content


# ---------------------------------------------------------------------------
# write_command
# ---------------------------------------------------------------------------


def test_cursor_write_command(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    client = CursorClient(tmp_path)
    client.write_command("shortcut.md", "Run command", Path("shortcut.md"), store)
    cmd_path = tmp_path / ".cursor" / "commands" / "shortcut.md"
    assert cmd_path.exists()
    assert "Run command" in cmd_path.read_text(encoding="utf-8")


def test_cursor_write_command_mdc(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    client = CursorClient(tmp_path)
    client.write_command("guide.mdc", "Guide content", Path("guide.mdc"), store)
    cmd_path = tmp_path / ".cursor" / "rules" / "guide.mdc"
    assert cmd_path.exists()
    assert "Guide content" in cmd_path.read_text(encoding="utf-8")


def test_codex_write_command(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    client = CodexClient(tmp_path)
    client.write_command("shortcut.md", "Run command", Path("shortcut.md"), store)
    cmd_path = tmp_path / ".codex" / "commands" / "shortcut.md"
    assert cmd_path.exists()
    assert "Run command" in cmd_path.read_text(encoding="utf-8")


def test_gemini_write_command(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    client = GeminiClient(tmp_path)
    client.write_command("shortcut.md", "Run command", Path("shortcut.md"), store)
    cmd_path = tmp_path / ".gemini" / "commands" / "shortcut.md"
    assert cmd_path.exists()
    assert "Run command" in cmd_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# sync_client_config — mode variations
# ---------------------------------------------------------------------------


def test_codex_client_config_normal(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    client = CodexClient(tmp_path)
    client.sync_client_config({"mode": "normal", "subagents": True}, store)
    data = tomllib.loads((tmp_path / ".codex" / "config.toml").read_text(encoding="utf-8"))
    assert data["approval_policy"] == "untrusted"
    assert data["sandbox_mode"] == "danger-full-access"
    assert data["features"]["multi_agent"] is True


def test_codex_client_config_strict(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    client = CodexClient(tmp_path)
    client.sync_client_config({"mode": "strict"}, store)
    data = tomllib.loads((tmp_path / ".codex" / "config.toml").read_text(encoding="utf-8"))
    assert data["approval_policy"] == "on-request"
    assert data["sandbox_mode"] == "read-only"


def test_codex_client_config_experimental(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    client = CodexClient(tmp_path)
    client.sync_client_config({"mode": "normal", "experimental": True}, store)
    data = tomllib.loads((tmp_path / ".codex" / "config.toml").read_text(encoding="utf-8"))
    assert data["suppress_unstable_features_warning"] is True


def test_cursor_client_config_strict(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    client = CursorClient(tmp_path)
    client.sync_client_config({"mode": "strict"}, store)
    cfg = json.loads((tmp_path / ".cursor" / "cli-config.json").read_text(encoding="utf-8"))
    assert cfg["permissions"]["allow"] == []


def test_gemini_client_config_normal(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    client = GeminiClient(tmp_path)
    client.sync_client_config({"mode": "normal", "subagents": True}, store)
    data = json.loads((tmp_path / ".gemini" / "settings.json").read_text(encoding="utf-8"))
    assert data["general"]["defaultApprovalMode"] == "auto_edit"
    assert data["experimental"]["enableAgents"] is True
    assert data["tools"]["sandbox"] is False


def test_gemini_client_config_strict(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    client = GeminiClient(tmp_path)
    client.sync_client_config({"mode": "strict"}, store)
    data = json.loads((tmp_path / ".gemini" / "settings.json").read_text(encoding="utf-8"))
    assert data["general"]["defaultApprovalMode"] == "plan"
    assert data["experimental"]["plan"] is True
    assert data["tools"]["sandbox"] is True


def test_gemini_client_config_yolo(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    client = GeminiClient(tmp_path)
    client.sync_client_config({"mode": "yolo"}, store)
    data = json.loads((tmp_path / ".gemini" / "settings.json").read_text(encoding="utf-8"))
    assert data["general"]["defaultApprovalMode"] == "yolo"
    assert data["tools"]["sandbox"] is False


# ---------------------------------------------------------------------------
# sync_mcp — stale server cleanup
# ---------------------------------------------------------------------------


def test_codex_sync_mcp_cleans_stale_servers(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    client = CodexClient(tmp_path)
    client.sync_mcp(
        {"s1": {"method": "stdio", "command": "a"}, "s2": {"method": "stdio", "command": "b"}},
        {"servers": {}},
        store,
    )
    config_path = tmp_path / ".codex" / "config.toml"
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert "s1" in data["mcp_servers"]
    assert "s2" in data["mcp_servers"]

    client.sync_mcp({"s1": {"method": "stdio", "command": "a"}}, {"servers": {}}, store)
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert "s1" in data["mcp_servers"]
    assert "s2" not in data["mcp_servers"]


def test_codex_sync_mcp_no_bearer_cleans_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    client = CodexClient(tmp_path)
    client.sync_mcp({"s1": {"method": "stdio", "command": "a"}}, {"servers": {}}, store)
    mcp_env = tmp_path / ".codex" / "mcp.env"
    assert not mcp_env.exists() or not mcp_env.read_text(encoding="utf-8").strip()
