"""MCP sync flow."""

from __future__ import annotations

from ai_sync.clients import CLIENTS
from ai_sync.display import Display


def server_applies_to_client(server: dict, client_name: str, display: Display) -> bool:
    if not server.get("enabled", True):
        return False
    clients = server.get("clients")
    if clients is None:
        return True
    if not isinstance(clients, list):
        display.print(
            f"Warning: 'clients' should be a list, got {type(clients).__name__}; skipping server",
            style="warning",
        )
        return False
    return client_name in clients


def sync_mcp_servers(manifest: dict, display: Display) -> None:
    servers = manifest.get("servers") or {}
    if not servers:
        display.print("MCP Servers: skipping (no servers)", style="dim")
        return
    display.rule("Syncing MCP Servers")
    secrets: dict = {"servers": {}}
    sync_errors: list[str] = []
    for client in CLIENTS:
        try:
            client.sync_mcp(
                servers,
                secrets,
                lambda server, client_name, d=display: server_applies_to_client(server, client_name, d),
            )
        except Exception as exc:
            sync_errors.append(f"{client.name}: {exc}")
            display.print(f"  Warning: MCP sync failed for {client.name}: {exc}", style="warning")
    if sync_errors:
        display.print(f"  {len(sync_errors)} client(s) had MCP sync errors (see above)", style="warning")

    instructions = (manifest.get("global") or {}).get("instructions")
    if instructions and isinstance(instructions, str) and instructions.strip():
        for client in CLIENTS:
            client.sync_mcp_instructions(instructions.strip())

    server_ids = [sid for sid, srv in servers.items() if srv.get("enabled", True)]
    display.table(
        ("Item", "Value"),
        [("Servers", ", ".join(server_ids) if server_ids else "—"), ("Clients", ", ".join(c.name for c in CLIENTS))],
    )
