from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_sync.clients.codex import CodexClient
from ai_sync.clients.cursor import CursorClient
from ai_sync.clients.gemini import GeminiClient

import tomli as tomllib


# ---------------------------------------------------------------------------
# sync_mcp + sync_client_config (integration)
# ---------------------------------------------------------------------------


def test_codex_sync_mcp_and_config(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    client = CodexClient()
    servers = {
        "s1": {
            "method": "stdio",
            "command": "npx",
            "args": ["x"],
            "env": {"TOKEN": "secret"},
            "bearer_token_env_var": "TOKEN",
        }
    }
    client.sync_mcp(servers, {"servers": {}}, lambda *_: True)
    config_path = tmp_path / ".codex" / "config.toml"
    assert config_path.exists()
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert "mcp_servers" in data
    mcp_env = tmp_path / ".codex" / "mcp.env"
    assert mcp_env.exists()
    assert "export TOKEN=" in mcp_env.read_text(encoding="utf-8")

    client.sync_client_config({"mode": "yolo", "subagents": True})
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert data["approval_policy"] == "never"
    assert data["sandbox_mode"] == "danger-full-access"


def test_cursor_sync_mcp_and_config(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    client = CursorClient()
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
    client.sync_mcp(servers, secrets, lambda *_: True)
    mcp_path = tmp_path / ".cursor" / "mcp.json"
    data = json.loads(mcp_path.read_text(encoding="utf-8"))
    assert data["mcpServers"]["s1"]["url"] == "https://x"
    assert data["mcpServers"]["s1"]["auth"]["token"] == "secret"
    client.sync_client_config({"mode": "yolo"})
    cfg = json.loads((tmp_path / ".cursor" / "cli-config.json").read_text(encoding="utf-8"))
    assert "Shell(*)" in cfg["permissions"]["allow"]


def test_gemini_sync_mcp_and_fallback(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    client = GeminiClient()
    servers = {
        "s1": {
            "method": "http",
            "httpUrl": "https://x",
            "oauth": {"enabled": True, "scopes": ["a"]},
        }
    }
    secrets = {"servers": {"s1": {"oauth": {"clientId": "id", "clientSecret": "secret"}}}}
    client.sync_mcp(servers, secrets, lambda *_: True)
    settings_path = tmp_path / ".gemini" / "settings.json"
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    assert data["mcpServers"]["s1"]["oauth"]["clientId"] == "id"

    settings_path.write_text(json.dumps({}), encoding="utf-8")
    client.enable_subagents_fallback()
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    assert data["experimental"]["enableAgents"] is True

    client.sync_mcp_instructions("Use work MCP")
    gemini_md = tmp_path / ".gemini" / "GEMINI.md"
    assert "MCP Server Instructions" in gemini_md.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# write_agent
# ---------------------------------------------------------------------------


def test_codex_write_agent(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    client = CodexClient()
    meta = {"reasoning_effort": "medium", "web_search": False}
    client.write_agent("my-agent", meta, "Do the thing", Path("agent.md"))
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
    client = CursorClient()
    meta = {"name": "my-agent", "description": "A test agent", "is_background": True}
    client.write_agent("my-agent", meta, "Task content", Path("agent.md"))
    agent_path = tmp_path / ".cursor" / "agents" / "my-agent.md"
    assert agent_path.exists()
    content = agent_path.read_text(encoding="utf-8")
    assert "Task content" in content
    assert "is_background: true" in content
    assert '"A test agent"' in content


def test_gemini_write_agent(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    client = GeminiClient()
    meta = {"description": "Test desc", "tools": ["search", "browse"]}
    client.write_agent("my-agent", meta, "Prompt body", Path("agent.md"))
    agent_path = tmp_path / ".gemini" / "agents" / "my-agent.md"
    assert agent_path.exists()
    content = agent_path.read_text(encoding="utf-8")
    assert "Prompt body" in content
    assert "my-agent" in content
    assert '["search", "browse"]' in content


# ---------------------------------------------------------------------------
# sync_mcp_instructions
# ---------------------------------------------------------------------------


def test_codex_sync_mcp_instructions(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    client = CodexClient()
    client.sync_mcp_instructions("Pick the work MCP for corporate queries.")
    config_path = tmp_path / ".codex" / "config.toml"
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert "Pick the work MCP" in data["developer_instructions"]


def test_codex_sync_mcp_instructions_blank_is_noop(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    client = CodexClient()
    client.sync_mcp_instructions("")
    assert not (tmp_path / ".codex" / "config.toml").exists()


def test_cursor_sync_mcp_instructions(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    client = CursorClient()
    client.sync_mcp_instructions("Use personal MCP for side-projects.")
    rules_file = tmp_path / ".cursor" / "rules" / "mcp-instructions.mdc"
    assert rules_file.exists()
    content = rules_file.read_text(encoding="utf-8")
    assert "Use personal MCP" in content
    assert "alwaysApply: true" in content


# ---------------------------------------------------------------------------
# sync_client_config — mode variations
# ---------------------------------------------------------------------------


def test_codex_client_config_normal(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    client = CodexClient()
    client.sync_client_config({"mode": "normal", "subagents": True})
    data = tomllib.loads((tmp_path / ".codex" / "config.toml").read_text(encoding="utf-8"))
    assert data["approval_policy"] == "untrusted"
    assert data["sandbox_mode"] == "danger-full-access"
    assert data["features"]["multi_agent"] is True


def test_codex_client_config_strict(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    client = CodexClient()
    client.sync_client_config({"mode": "strict"})
    data = tomllib.loads((tmp_path / ".codex" / "config.toml").read_text(encoding="utf-8"))
    assert data["approval_policy"] == "on-request"
    assert data["sandbox_mode"] == "read-only"


def test_codex_client_config_experimental(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    client = CodexClient()
    client.sync_client_config({"mode": "normal", "experimental": True})
    data = tomllib.loads((tmp_path / ".codex" / "config.toml").read_text(encoding="utf-8"))
    assert data["suppress_unstable_features_warning"] is True


def test_cursor_client_config_strict(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    client = CursorClient()
    client.sync_client_config({"mode": "strict"})
    cfg = json.loads((tmp_path / ".cursor" / "cli-config.json").read_text(encoding="utf-8"))
    assert cfg["permissions"]["allow"] == []


def test_gemini_client_config_normal(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    client = GeminiClient()
    client.sync_client_config({"mode": "normal", "subagents": True})
    data = json.loads((tmp_path / ".gemini" / "settings.json").read_text(encoding="utf-8"))
    assert data["general"]["defaultApprovalMode"] == "auto_edit"
    assert data["experimental"]["enableAgents"] is True
    assert data["tools"]["sandbox"] is False


def test_gemini_client_config_strict(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    client = GeminiClient()
    client.sync_client_config({"mode": "strict"})
    data = json.loads((tmp_path / ".gemini" / "settings.json").read_text(encoding="utf-8"))
    assert data["general"]["defaultApprovalMode"] == "plan"
    assert data["experimental"]["plan"] is True
    assert data["tools"]["sandbox"] is True


def test_gemini_client_config_yolo(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    client = GeminiClient()
    client.sync_client_config({"mode": "yolo"})
    data = json.loads((tmp_path / ".gemini" / "settings.json").read_text(encoding="utf-8"))
    assert data["general"]["defaultApprovalMode"] == "yolo"
    assert data["tools"]["sandbox"] is False


# ---------------------------------------------------------------------------
# sync_mcp — stale server cleanup
# ---------------------------------------------------------------------------


def test_codex_sync_mcp_cleans_stale_servers(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    client = CodexClient()
    client.sync_mcp(
        {"s1": {"method": "stdio", "command": "a"}, "s2": {"method": "stdio", "command": "b"}},
        {"servers": {}},
        lambda *_: True,
    )
    config_path = tmp_path / ".codex" / "config.toml"
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert "s1" in data["mcp_servers"]
    assert "s2" in data["mcp_servers"]

    client.sync_mcp({"s1": {"method": "stdio", "command": "a"}}, {"servers": {}}, lambda *_: True)
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert "s1" in data["mcp_servers"]
    assert "s2" not in data["mcp_servers"]


def test_codex_sync_mcp_no_bearer_cleans_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    client = CodexClient()
    client.sync_mcp({"s1": {"method": "stdio", "command": "a"}}, {"servers": {}}, lambda *_: True)
    mcp_env = tmp_path / ".codex" / "mcp.env"
    assert not mcp_env.exists() or not mcp_env.read_text(encoding="utf-8").strip()


def test_gemini_enable_subagents_fallback_noop_if_missing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    client = GeminiClient()
    client.enable_subagents_fallback()
    assert not (tmp_path / ".gemini" / "settings.json").exists()
