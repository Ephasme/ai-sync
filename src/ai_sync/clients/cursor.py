"""Cursor client adapter."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from ai_sync.state_store import StateStore
from ai_sync.track_write import DELETE, WriteSpec, track_write_blocks

from .base import Client


class CursorClient(Client):
    @property
    def name(self) -> str:
        return "cursor"

    @property
    def config_dir(self) -> Path:
        return Path.home() / ".cursor"

    def write_agent(self, slug: str, meta: dict, raw_content: str, prompt_src_path: Path) -> None:
        agent_path = self.get_agents_dir() / f"{slug}.md"
        content = f"""---
name: {json.dumps(meta.get("name", slug))}
description: {json.dumps(meta.get("description", "AI Agent"))}
model: auto
is_background: {"true" if meta.get("is_background", False) else "false"}
---

{raw_content}
"""
        track_write_blocks(
            [
                WriteSpec(
                    file_path=agent_path,
                    format="text",
                    target=f"ai-sync:agent:{slug}",
                    value=content,
                )
            ]
        )

    def write_command(self, slug: str, raw_content: str, command_src_path: Path) -> None:
        if command_src_path.suffix == ".mdc":
            target_dir = self.config_dir / "rules"
        else:
            target_dir = self.config_dir / "commands"
        target_path = target_dir / command_src_path
        track_write_blocks(
            [
                WriteSpec(
                    file_path=target_path,
                    format="text",
                    target=f"ai-sync:command:{slug}",
                    value=raw_content,
                )
            ]
        )

    def _build_mcp_entry(self, server_id: str, server: dict, secrets: dict) -> dict:
        secret_srv = self._get_secret_for_server(server_id, secrets)
        method = server.get("method", "stdio")
        entry: dict = {}
        if method == "stdio":
            entry["command"] = server.get("command", "npx")
            entry["args"] = server.get("args", [])
        env = self._build_mcp_env(server, secret_srv)
        if env:
            entry["env"] = env
        auth_cfg: dict = {}
        if isinstance(server.get("auth"), dict):
            auth_cfg.update(server["auth"])
        if isinstance(secret_srv.get("auth"), dict):
            auth_cfg.update(secret_srv["auth"])
        if auth_cfg:
            entry["auth"] = {k: str(v) if v is not None else "" for k, v in auth_cfg.items()}
        if method in ("http", "sse"):
            url = server.get("url") or server.get("httpUrl")
            if url:
                entry["url"] = url
        if server.get("trust") is True:
            entry["trust"] = True
        if server.get("description"):
            entry["description"] = str(server["description"])
        if "timeout_seconds" in server and server.get("timeout_seconds") is not None:
            try:
                sec = float(server["timeout_seconds"])
                if sec < 0:
                    raise ValueError
                entry["timeout"] = int(sec * 1000)
            except (TypeError, ValueError):
                print(
                    f"  Warning: Invalid timeout_seconds for server '{server_id}': {server['timeout_seconds']!r}"
                )
        return entry

    def sync_mcp(self, servers: dict, secrets: dict, for_client: Callable[[dict, str], bool]) -> None:
        cursor_mcp: dict = {}
        for sid, srv in servers.items():
            if for_client(srv, self.name):
                cursor_mcp[sid] = self._build_mcp_entry(sid, srv, secrets)
        mcp_path = self.config_dir / "mcp.json"
        specs: list[WriteSpec] = [
            WriteSpec(
                file_path=mcp_path,
                format="json",
                target=f"/mcpServers/{sid}",
                value=entry,
            )
            for sid, entry in cursor_mcp.items()
        ]
        store = StateStore()
        store.load()
        existing_targets = store.list_targets(mcp_path, "json", "/mcpServers/")
        existing_ids = {t.split("/", 2)[2] for t in existing_targets if t.count("/") >= 2}
        for sid in sorted(existing_ids - set(cursor_mcp.keys())):
            specs.append(
                WriteSpec(
                    file_path=mcp_path,
                    format="json",
                    target=f"/mcpServers/{sid}",
                    value=DELETE,
                )
            )
        if specs:
            track_write_blocks(specs)
        if any(e.get("env") or e.get("auth") for e in cursor_mcp.values()):
            self._set_restrictive_permissions(mcp_path)
            self._warn_plaintext_secrets(mcp_path)

    def _build_client_config(self, settings: dict) -> dict:
        mode = settings.get("mode") or "normal"
        if mode in {"normal", "yolo"}:
            return {"permissions": {"allow": ["Shell(*)", "Read(*)", "Write(*)", "WebFetch(*)", "Mcp(*:*)"], "deny": []}}
        return {"permissions": {"allow": [], "deny": []}}

    def sync_client_config(self, settings: dict) -> None:
        updates = self._build_client_config(settings)
        if not updates:
            return
        config_path = self.config_dir / "cli-config.json"
        permissions = updates.get("permissions", {})
        specs = [
            WriteSpec(
                file_path=config_path,
                format="json",
                target="/permissions/allow",
                value=permissions.get("allow", []),
            ),
            WriteSpec(
                file_path=config_path,
                format="json",
                target="/permissions/deny",
                value=permissions.get("deny", []),
            ),
        ]
        track_write_blocks(specs)

    def sync_mcp_instructions(self, instructions: str) -> None:
        if not instructions or not instructions.strip():
            return
        rules_dir = self.config_dir / "rules"
        content = f"""---
description: MCP server selection guidance (e.g. which Google Workspace to use)
alwaysApply: true
---

# MCP Server Instructions

{instructions.strip()}
"""
        track_write_blocks(
            [
                WriteSpec(
                    file_path=rules_dir / "mcp-instructions.mdc",
                    format="text",
                    target="ai-sync:mcp-instructions",
                    value=content,
                )
            ]
        )
