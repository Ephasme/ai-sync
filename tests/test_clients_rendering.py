from pathlib import Path

from ai_sync.clients.codex import CodexClient
from ai_sync.clients.cursor import CursorClient
from ai_sync.clients.gemini import GeminiClient


# ---------------------------------------------------------------------------
# _build_mcp_entry
# ---------------------------------------------------------------------------


def test_cursor_build_mcp_entry() -> None:
    client = CursorClient(Path("/tmp/test"))
    entry = client._build_mcp_entry(
        "s",
        {"method": "stdio", "command": "npx", "args": ["x"], "env": {"K": "V"}, "timeout_seconds": 1},
        {"servers": {}},
    )
    assert entry["command"] == "npx"
    assert entry["env"]["K"] == "V"
    assert entry["timeout"] == 1000
    assert entry["disabled"] is False


def test_codex_build_mcp_entry_http() -> None:
    client = CodexClient(Path("/tmp/test"))
    entry = client._build_mcp_entry(
        "s",
        {"method": "http", "url": "https://x"},
        {"servers": {}},
    )
    assert entry["url"] == "https://x"


def test_gemini_build_mcp_entry_oauth() -> None:
    client = GeminiClient(Path("/tmp/test"))
    entry = client._build_mcp_entry(
        "s",
        {
            "method": "http",
            "httpUrl": "https://x",
            "oauth": {"enabled": True, "clientId": "id", "clientSecret": "secret", "scopes": ["a"]},
        },
        {"servers": {}},
    )
    assert entry["oauth"]["clientId"] == "id"


def test_codex_build_mcp_entry_with_description_and_timeout() -> None:
    client = CodexClient(Path("/tmp/test"))
    entry = client._build_mcp_entry(
        "s",
        {
            "method": "stdio",
            "command": "node",
            "args": ["server.js"],
            "description": "My server",
            "timeout_seconds": 30,
        },
        {"servers": {}},
    )
    assert entry["description"] == "My server"
    assert entry["startup_timeout_sec"] == 30
    assert entry["tool_timeout_sec"] == 30


def test_codex_build_mcp_entry_bearer_token_env_var() -> None:
    client = CodexClient(Path("/tmp/test"))
    entry = client._build_mcp_entry(
        "s",
        {"method": "http", "url": "https://x", "bearer_token_env_var": "MY_TOKEN"},
        {"servers": {}},
    )
    assert entry["bearer_token_env_var"] == "MY_TOKEN"


def test_cursor_build_mcp_entry_http_with_trust() -> None:
    client = CursorClient(Path("/tmp/test"))
    entry = client._build_mcp_entry(
        "s",
        {"method": "http", "url": "https://x", "trust": True, "description": "A service"},
        {"servers": {}},
    )
    assert entry["url"] == "https://x"
    assert entry["trust"] is True
    assert entry["description"] == "A service"
    assert "command" not in entry


def test_gemini_build_mcp_entry_stdio() -> None:
    client = GeminiClient(Path("/tmp/test"))
    entry = client._build_mcp_entry(
        "s",
        {"method": "stdio", "command": "python", "args": ["-m", "srv"], "trust": True, "timeout_seconds": 10},
        {"servers": {}},
    )
    assert entry["command"] == "python"
    assert entry["args"] == ["-m", "srv"]
    assert entry["trust"] is True
    assert entry["timeout"] == 10_000


def test_gemini_build_mcp_entry_http_urls() -> None:
    client = GeminiClient(Path("/tmp/test"))
    entry = client._build_mcp_entry(
        "s",
        {"method": "http", "url": "https://a", "httpUrl": "https://b", "description": "D"},
        {"servers": {}},
    )
    assert entry["url"] == "https://a"
    assert entry["httpUrl"] == "https://b"
    assert entry["description"] == "D"


def test_codex_build_mcp_entry_env_merges_secrets() -> None:
    client = CodexClient(Path("/tmp/test"))
    entry = client._build_mcp_entry(
        "s",
        {"method": "stdio", "command": "a", "env": {"PUBLIC": "1"}},
        {"servers": {"s": {"env": {"SECRET": "2"}}}},
    )
    assert entry["env"]["PUBLIC"] == "1"
    assert entry["env"]["SECRET"] == "2"


# ---------------------------------------------------------------------------
# _build_client_config (unit, no filesystem)
# ---------------------------------------------------------------------------


class TestCodexBuildClientConfig:
    def test_yolo(self) -> None:
        cfg = CodexClient(Path("/tmp/test"))._build_client_config({"mode": "yolo"})
        assert cfg["approval_policy"] == "never"
        assert cfg["sandbox_mode"] == "danger-full-access"

    def test_normal(self) -> None:
        cfg = CodexClient(Path("/tmp/test"))._build_client_config({"mode": "normal"})
        assert cfg["approval_policy"] == "untrusted"

    def test_strict(self) -> None:
        cfg = CodexClient(Path("/tmp/test"))._build_client_config({"mode": "strict"})
        assert cfg["approval_policy"] == "on-request"
        assert cfg["sandbox_mode"] == "read-only"

    def test_unknown_mode(self) -> None:
        cfg = CodexClient(Path("/tmp/test"))._build_client_config({"mode": "custom"})
        assert cfg["approval_policy"] == "on-request"
        assert cfg["sandbox_mode"] == "workspace-write"

    def test_experimental_flag(self) -> None:
        cfg = CodexClient(Path("/tmp/test"))._build_client_config({"mode": "normal", "experimental": True})
        assert cfg["suppress_unstable_features_warning"] is True

    def test_subagents(self) -> None:
        cfg = CodexClient(Path("/tmp/test"))._build_client_config({"mode": "normal", "subagents": True})
        assert cfg["features"]["multi_agent"] is True
        assert cfg["features"]["child_agents_md"] is True


class TestCursorBuildClientConfig:
    def test_yolo(self) -> None:
        cfg = CursorClient(Path("/tmp/test"))._build_client_config({"mode": "yolo"})
        assert "Shell(*)" in cfg["permissions"]["allow"]

    def test_normal(self) -> None:
        cfg = CursorClient(Path("/tmp/test"))._build_client_config({"mode": "normal"})
        assert "Shell(*)" in cfg["permissions"]["allow"]

    def test_strict(self) -> None:
        cfg = CursorClient(Path("/tmp/test"))._build_client_config({"mode": "strict"})
        assert cfg["permissions"]["allow"] == []


class TestGeminiBuildClientConfig:
    def test_normal(self) -> None:
        cfg = GeminiClient(Path("/tmp/test"))._build_client_config({"mode": "normal"})
        assert cfg["general"]["defaultApprovalMode"] == "auto_edit"
        assert cfg["tools"]["sandbox"] is False

    def test_strict(self) -> None:
        cfg = GeminiClient(Path("/tmp/test"))._build_client_config({"mode": "strict"})
        assert cfg["general"]["defaultApprovalMode"] == "plan"
        assert cfg["experimental"]["plan"] is True
        assert cfg["tools"]["sandbox"] is True

    def test_yolo(self) -> None:
        cfg = GeminiClient(Path("/tmp/test"))._build_client_config({"mode": "yolo"})
        assert cfg["general"]["defaultApprovalMode"] == "yolo"
        assert cfg["tools"]["sandbox"] is False

    def test_subagents(self) -> None:
        cfg = GeminiClient(Path("/tmp/test"))._build_client_config({"mode": "normal", "subagents": True})
        assert cfg["experimental"]["enableAgents"] is True

    def test_sandbox_from_tools_setting(self) -> None:
        cfg = GeminiClient(Path("/tmp/test"))._build_client_config({"mode": "unknown", "tools": {"sandbox": True}})
        assert cfg["tools"]["sandbox"] is True
