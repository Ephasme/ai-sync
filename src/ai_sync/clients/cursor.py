"""Cursor client adapter."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from ai_sync.helpers import (
    deep_merge,
    ensure_dir,
    write_content_if_different,
)

from .base import Client


class CursorClient(Client):
    @property
    def name(self) -> str:
        return "cursor"

    @property
    def config_dir(self) -> Path:
        return Path.home() / ".cursor"

    def write_agent(self, slug: str, meta: dict, raw_content: str, prompt_src_path: Path) -> None:
        ensure_dir(self.get_agents_dir())
        agent_path = self.get_agents_dir() / f"{slug}.md"
        content = f"""---
name: {json.dumps(meta.get("name", slug))}
description: {json.dumps(meta.get("description", "AI Agent"))}
model: auto
is_background: {"true" if meta.get("is_background", False) else "false"}
---

{raw_content}
"""
        write_content_if_different(agent_path, content)

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
        ensure_dir(self.config_dir)
        mcp_path = self.config_dir / "mcp.json"
        existing = self._read_json_config(mcp_path)
        existing["mcpServers"] = self._merge_managed_servers(existing.get("mcpServers", {}), cursor_mcp)
        write_content_if_different(mcp_path, self._write_json_config(existing))
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
        ensure_dir(self.config_dir)
        config_path = self.config_dir / "cli-config.json"
        existing = self._read_json_config(config_path)
        write_content_if_different(config_path, self._write_json_config(deep_merge(existing, updates)))

    def sync_mcp_instructions(self, instructions: str) -> None:
        if not instructions or not instructions.strip():
            return
        rules_dir = self.config_dir / "rules"
        ensure_dir(rules_dir)
        content = f"""---
description: MCP server selection guidance (e.g. which Google Workspace to use)
alwaysApply: true
---

# MCP Server Instructions

{instructions.strip()}
"""
        write_content_if_different(rules_dir / "mcp-instructions.mdc", content)
