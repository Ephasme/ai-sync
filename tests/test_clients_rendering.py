from ai_sync.clients.codex import CodexClient
from ai_sync.clients.cursor import CursorClient
from ai_sync.clients.gemini import GeminiClient


def test_cursor_build_mcp_entry() -> None:
    client = CursorClient()
    entry = client._build_mcp_entry(
        "s",
        {"method": "stdio", "command": "npx", "args": ["x"], "env": {"K": "V"}, "timeout": 1},
        {"servers": {}},
    )
    assert entry["command"] == "npx"
    assert entry["env"]["K"] == "V"
    assert entry["timeout"] == 1000


def test_codex_build_mcp_entry_http() -> None:
    client = CodexClient()
    entry = client._build_mcp_entry(
        "s",
        {"method": "http", "url": "https://x", "enabled": True},
        {"servers": {}},
    )
    assert entry["enabled"] is True
    assert entry["url"] == "https://x"


def test_gemini_build_mcp_entry_oauth() -> None:
    client = GeminiClient()
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
