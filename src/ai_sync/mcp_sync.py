"""MCP sync flow."""

from __future__ import annotations

from collections.abc import Sequence

from ai_sync.clients.base import Client
from ai_sync.display import Display
from ai_sync.state_store import StateStore


def sync_mcp_servers(
    servers: dict,
    clients: Sequence[Client],
    secrets: dict,
    store: StateStore,
    display: Display,
) -> None:
    if not servers:
        display.print("MCP Servers: skipping (no servers)", style="dim")
        return
    display.rule("Syncing MCP Servers")
    sync_errors: list[str] = []
    for client in clients:
        try:
            client.sync_mcp(servers, secrets, store)
        except Exception as exc:
            sync_errors.append(f"{client.name}: {exc}")
            display.print(f"  Warning: MCP sync failed for {client.name}: {exc}", style="warning")
    if sync_errors:
        display.print(f"  {len(sync_errors)} client(s) had MCP sync errors (see above)", style="warning")

    server_ids = list(servers.keys())
    display.table(
        ("Item", "Value"),
        [("Servers", ", ".join(server_ids) if server_ids else "—"), ("Clients", ", ".join(c.name for c in clients))],
    )
