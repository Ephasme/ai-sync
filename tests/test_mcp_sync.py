from __future__ import annotations

from ai_sync.data_classes.prepared_mcp_server import PreparedMcpServer
from ai_sync.services.mcp_artifact_service import _resolve_servers_for_client


def test_resolve_servers_for_client_applies_overrides() -> None:
    servers = {
        "s1": PreparedMcpServer(
            scoped_ref="co/s1",
            source_alias="co",
            server_id="s1",
            source_config={},
            runtime_config={
                "method": "stdio",
                "command": "npx",
                "headers": {"X-Base": "base"},
                "client_overrides": {
                    "cursor": {"headers": {"X-Extra": "val"}},
                },
            },
        ),
    }
    result = _resolve_servers_for_client(servers, "cursor")
    assert result["s1"]["headers"] == {"X-Base": "base", "X-Extra": "val"}
    assert "client_overrides" not in result["s1"]


def test_resolve_servers_for_client_no_overrides() -> None:
    servers = {
        "s1": PreparedMcpServer(
            scoped_ref="co/s1",
            source_alias="co",
            server_id="s1",
            source_config={},
            runtime_config={"method": "stdio", "command": "npx"},
        ),
    }
    result = _resolve_servers_for_client(servers, "codex")
    assert result["s1"]["method"] == "stdio"
    assert result["s1"]["command"] == "npx"
    assert "client_overrides" not in result["s1"]
