from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_sync.clients.codex import CodexClient
from ai_sync.clients.cursor import CursorClient
from ai_sync.clients.gemini import GeminiClient

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


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

    client.sync_client_config({"mode": "full-access", "subagents": True})
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
            "timeout": "1s",
        }
    }
    secrets = {"servers": {"s1": {"auth": {"token": "secret"}}}}
    client.sync_mcp(servers, secrets, lambda *_: True)
    mcp_path = tmp_path / ".cursor" / "mcp.json"
    data = json.loads(mcp_path.read_text(encoding="utf-8"))
    assert data["mcpServers"]["s1"]["url"] == "https://x"
    assert data["mcpServers"]["s1"]["auth"]["token"] == "secret"
    client.sync_client_config({"mode": "full-access"})
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
