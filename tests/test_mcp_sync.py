from __future__ import annotations

from ai_sync.mcp_sync import resolve_servers_for_client


def test_resolve_servers_for_client_applies_overrides() -> None:
    servers = {
        "s1": {
            "method": "stdio",
            "command": "npx",
            "env": {"TOKEN": "base"},
            "client_overrides": {
                "cursor": {"env": {"EXTRA": "val"}},
            },
        },
    }
    result = resolve_servers_for_client(servers, "cursor")
    assert result["s1"]["env"] == {"TOKEN": "base", "EXTRA": "val"}
    assert "client_overrides" not in result["s1"]


def test_resolve_servers_for_client_no_overrides() -> None:
    servers = {"s1": {"method": "stdio", "command": "npx"}}
    result = resolve_servers_for_client(servers, "codex")
    assert result["s1"]["method"] == "stdio"
    assert result["s1"]["command"] == "npx"
    assert "client_overrides" not in result["s1"]
