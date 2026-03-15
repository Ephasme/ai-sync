from __future__ import annotations

import json
from pathlib import Path

import tomli as tomllib

from ai_sync.clients.claude import ClaudeClient
from ai_sync.clients.codex import CodexClient
from ai_sync.clients.cursor import CursorClient
from ai_sync.clients.gemini import GeminiClient
from ai_sync.state_store import StateStore
from ai_sync.track_write import track_write_blocks


def test_codex_sync_mcp_and_config(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    client = CodexClient(tmp_path)
    servers = {
        "default-s1": {
            "method": "stdio",
            "command": "npx",
            "args": ["x"],
            "env": {"TOKEN": "secret"},
            "bearer_token_env_var": "TOKEN",
        }
    }
    specs = client.build_mcp_specs(servers, {"servers": {}})
    track_write_blocks(specs, store)
    config_path = tmp_path / ".codex" / "config.toml"
    assert config_path.exists()
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert "mcp_servers" in data
    mcp_env = tmp_path / ".codex" / "mcp.env"
    assert not mcp_env.exists()

    specs = client.build_client_config_specs({"mode": "yolo", "subagents": True})
    track_write_blocks(specs, store)
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert data["approval_policy"] == "never"
    assert data["sandbox_mode"] == "danger-full-access"


def test_cursor_sync_mcp_and_config(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    client = CursorClient(tmp_path)
    servers = {
        "default-s1": {
            "method": "http",
            "url": "https://x",
            "trust": True,
            "auth": {"token": "public"},
            "env": {"A": "B"},
            "timeout_seconds": 1,
        }
    }
    secrets = {"servers": {"default-s1": {"auth": {"token": "secret"}}}}
    specs = client.build_mcp_specs(servers, secrets)
    track_write_blocks(specs, store)
    mcp_path = tmp_path / ".cursor" / "mcp.json"
    data = json.loads(mcp_path.read_text(encoding="utf-8"))
    assert data["mcpServers"]["default-s1"]["url"] == "https://x"
    assert data["mcpServers"]["default-s1"]["auth"]["token"] == "secret"

    specs = client.build_client_config_specs({"mode": "yolo"})
    track_write_blocks(specs, store)
    cfg = json.loads((tmp_path / ".cursor" / "cli-config.json").read_text(encoding="utf-8"))
    assert "Shell(*)" in cfg["permissions"]["allow"]


def test_gemini_sync_mcp(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    client = GeminiClient(tmp_path)
    servers = {
        "default-s1": {
            "method": "http",
            "httpUrl": "https://x",
            "oauth": {"enabled": True, "scopes": ["a"]},
        }
    }
    secrets = {"servers": {"default-s1": {"oauth": {"clientId": "id", "clientSecret": "secret"}}}}
    specs = client.build_mcp_specs(servers, secrets)
    track_write_blocks(specs, store)
    settings_path = tmp_path / ".gemini" / "settings.json"
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    assert data["mcpServers"]["default-s1"]["oauth"]["clientId"] == "id"


def test_codex_write_agent(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    client = CodexClient(tmp_path)
    meta = {"reasoning_effort": "medium", "web_search": False}
    specs = client.build_agent_specs("default", "my-agent", meta, "Do the thing", Path("agent.md"))
    track_write_blocks(specs, store)
    agent_dir = tmp_path / ".codex" / "agents" / "default-my-agent"
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
    specs = client.build_agent_specs("default", "my-agent", meta, "Task content", Path("agent.md"))
    track_write_blocks(specs, store)
    agent_path = tmp_path / ".cursor" / "agents" / "default-my-agent.md"
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
    specs = client.build_agent_specs("default", "my-agent", meta, "Prompt body", Path("agent.md"))
    track_write_blocks(specs, store)
    agent_path = tmp_path / ".gemini" / "agents" / "default-my-agent.md"
    assert agent_path.exists()
    content = agent_path.read_text(encoding="utf-8")
    assert "Prompt body" in content
    assert "default-my-agent" in content
    assert '["search", "browse"]' in content


def test_cursor_write_command(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    client = CursorClient(tmp_path)
    meta = {"description": "A shortcut command"}
    specs = client.build_command_specs("default", "review/shortcut", meta, "Run command", "review/shortcut")
    track_write_blocks(specs, store)
    cmd_path = tmp_path / ".cursor" / "commands" / "review" / "default-shortcut.md"
    assert cmd_path.exists()
    assert "Run command" in cmd_path.read_text(encoding="utf-8")


def test_codex_write_command(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    client = CodexClient(tmp_path)
    meta = {"description": "A shortcut command"}
    specs = client.build_command_specs("default", "review/shortcut", meta, "Run command", "review/shortcut")
    track_write_blocks(specs, store)
    cmd_path = tmp_path / ".codex" / "commands" / "review" / "default-shortcut.md"
    assert cmd_path.exists()
    assert "Run command" in cmd_path.read_text(encoding="utf-8")


def test_gemini_write_command(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    client = GeminiClient(tmp_path)
    meta = {"description": "A shortcut command"}
    specs = client.build_command_specs("default", "review/shortcut", meta, "Run command", "review/shortcut")
    track_write_blocks(specs, store)
    cmd_path = tmp_path / ".gemini" / "commands" / "review" / "default-shortcut.toml"
    assert cmd_path.exists()
    content = cmd_path.read_text(encoding="utf-8")
    assert 'description = "A shortcut command"' in content
    assert 'prompt = "Run command"' in content


def test_claude_sync_mcp_and_config(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    client = ClaudeClient(tmp_path)
    servers = {
        "default-s1": {
            "method": "http",
            "url": "https://x",
            "headers": {"Authorization": "Bearer token"},
            "env": {"A": "B"},
        }
    }
    secrets = {"servers": {"default-s1": {"env": {"SECRET": "1"}}}}
    specs = client.build_mcp_specs(servers, secrets)
    track_write_blocks(specs, store)
    data = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    assert data["mcpServers"]["default-s1"]["type"] == "http"
    assert data["mcpServers"]["default-s1"]["url"] == "https://x"
    assert data["mcpServers"]["default-s1"]["env"]["SECRET"] == "1"

    specs = client.build_client_config_specs({"mode": "strict"})
    track_write_blocks(specs, store)
    cfg = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert cfg["$schema"] == "https://json.schemastore.org/claude-code-settings.json"
    assert cfg["permissions"]["allow"] == []


def test_claude_write_agent(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    client = ClaudeClient(tmp_path)
    meta = {"description": "A test agent"}
    specs = client.build_agent_specs("default", "my-agent", meta, "Task content", Path("agent.md"))
    track_write_blocks(specs, store)
    agent_path = tmp_path / ".claude" / "agents" / "default-my-agent.md"
    assert agent_path.exists()
    content = agent_path.read_text(encoding="utf-8")
    assert "Task content" in content
    assert "name: \"default-my-agent\"" in content
    assert '"A test agent"' in content


def test_claude_write_command(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    client = ClaudeClient(tmp_path)
    meta = {"description": "A shortcut command"}
    specs = client.build_command_specs("default", "review/shortcut", meta, "Run command", "review/shortcut")
    track_write_blocks(specs, store)
    cmd_path = tmp_path / ".claude" / "commands" / "review" / "default-shortcut.md"
    assert cmd_path.exists()
    assert "Run command" in cmd_path.read_text(encoding="utf-8")


def test_codex_client_config_normal(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    client = CodexClient(tmp_path)
    specs = client.build_client_config_specs({"mode": "normal", "subagents": True})
    track_write_blocks(specs, store)
    data = tomllib.loads((tmp_path / ".codex" / "config.toml").read_text(encoding="utf-8"))
    assert data["approval_policy"] == "untrusted"
    assert data["sandbox_mode"] == "danger-full-access"
    assert data["features"]["multi_agent"] is True


def test_codex_client_config_strict(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    client = CodexClient(tmp_path)
    specs = client.build_client_config_specs({"mode": "strict"})
    track_write_blocks(specs, store)
    data = tomllib.loads((tmp_path / ".codex" / "config.toml").read_text(encoding="utf-8"))
    assert data["approval_policy"] == "on-request"
    assert data["sandbox_mode"] == "read-only"


def test_codex_client_config_experimental(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    client = CodexClient(tmp_path)
    specs = client.build_client_config_specs({"mode": "normal", "experimental": True})
    track_write_blocks(specs, store)
    data = tomllib.loads((tmp_path / ".codex" / "config.toml").read_text(encoding="utf-8"))
    assert data["suppress_unstable_features_warning"] is True


def test_cursor_client_config_strict(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    client = CursorClient(tmp_path)
    specs = client.build_client_config_specs({"mode": "strict"})
    track_write_blocks(specs, store)
    cfg = json.loads((tmp_path / ".cursor" / "cli-config.json").read_text(encoding="utf-8"))
    assert cfg["permissions"]["allow"] == []


def test_gemini_client_config_normal(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    client = GeminiClient(tmp_path)
    specs = client.build_client_config_specs({"mode": "normal", "subagents": True})
    track_write_blocks(specs, store)
    data = json.loads((tmp_path / ".gemini" / "settings.json").read_text(encoding="utf-8"))
    assert data["general"]["defaultApprovalMode"] == "auto_edit"
    assert data["experimental"]["enableAgents"] is True
    assert data["tools"]["sandbox"] is False


def test_gemini_client_config_strict(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    client = GeminiClient(tmp_path)
    specs = client.build_client_config_specs({"mode": "strict"})
    track_write_blocks(specs, store)
    data = json.loads((tmp_path / ".gemini" / "settings.json").read_text(encoding="utf-8"))
    assert data["general"]["defaultApprovalMode"] == "plan"
    assert data["experimental"]["plan"] is True
    assert data["tools"]["sandbox"] is True


def test_gemini_client_config_yolo(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    client = GeminiClient(tmp_path)
    specs = client.build_client_config_specs({"mode": "yolo"})
    track_write_blocks(specs, store)
    data = json.loads((tmp_path / ".gemini" / "settings.json").read_text(encoding="utf-8"))
    assert data["general"]["defaultApprovalMode"] == "auto_edit"
    assert data["tools"]["sandbox"] is False


def test_codex_build_mcp_specs_multiple_servers(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    client = CodexClient(tmp_path)
    servers = {
        "default-s1": {"method": "stdio", "command": "a"},
        "default-s2": {"method": "stdio", "command": "b"},
    }
    specs = client.build_mcp_specs(servers, {"servers": {}})
    track_write_blocks(specs, store)
    config_path = tmp_path / ".codex" / "config.toml"
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert "default-s1" in data["mcp_servers"]
    assert "default-s2" in data["mcp_servers"]


def test_codex_build_mcp_specs_no_bearer(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    client = CodexClient(tmp_path)
    specs = client.build_mcp_specs({"default-s1": {"method": "stdio", "command": "a"}}, {"servers": {}})
    track_write_blocks(specs, store)
    mcp_env = tmp_path / ".codex" / "mcp.env"
    assert not mcp_env.exists() or not mcp_env.read_text(encoding="utf-8").strip()
