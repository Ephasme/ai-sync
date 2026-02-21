"""Cursor client adapter."""
import json
from pathlib import Path

from .base import Client
from helpers import deep_merge, ensure_dir, write_content_if_different


class CursorClient(Client):
    @property
    def name(self) -> str:
        return "cursor"

    @property
    def config_dir(self) -> Path:
        return Path.home() / ".cursor"

    def write_agent(
        self,
        slug: str,
        meta: dict,
        raw_content: str,
        prompt_src_path: Path,
    ) -> None:
        ensure_dir(self.get_agents_dir())
        agent_path = self.get_agents_dir() / f"{slug}.md"
        display_name = meta.get("name", slug)
        description = meta.get("description", "AI Agent")
        cursor_model = meta.get("models", {}).get("cursor", "gpt-5.2")
        is_background = "true" if meta.get("is_background", False) else "false"
        content = f"""---
name: {display_name}
description: {description}
model: {cursor_model}
is_background: {is_background}
---

{raw_content}
"""
        write_content_if_different(agent_path, content, backup=False)

    def _build_mcp_entry(self, server_id: str, server: dict, secrets: dict) -> dict:
        entry: dict = {
            "command": server.get("command", "npx"),
            "args": server.get("args", []),
        }
        secret_srv = secrets.get("servers", {}).get(server_id, {})
        if secret_srv.get("env"):
            entry["env"] = {k: str(v) if v is not None else "" for k, v in secret_srv["env"].items()}
        if secret_srv.get("auth"):
            entry["auth"] = {k: str(v) if v is not None else "" for k, v in secret_srv["auth"].items()}
        if server.get("method") in ("http", "sse"):
            entry["url"] = server.get("url", "")
        return entry

    def sync_mcp(self, servers: dict, secrets: dict, for_client) -> None:
        cursor_mcp: dict = {}
        for sid, srv in servers.items():
            if not for_client(srv, self.name):
                continue
            cursor_mcp[sid] = self._build_mcp_entry(sid, srv, secrets)
        if not cursor_mcp:
            return
        ensure_dir(self.config_dir)
        mcp_path = self.config_dir / "mcp.json"
        existing: dict = {}
        if mcp_path.exists():
            try:
                with open(mcp_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        merged = deep_merge(existing, {"mcpServers": cursor_mcp})
        write_content_if_different(
            mcp_path, json.dumps(merged, indent=2), backup=False
        )

    def _build_client_config(self, settings: dict) -> dict:
        mode = settings.get("mode", "ask")
        if mode == "full-access":
            return {"permissions": {"allow": ["Shell(*)", "Read(*)", "Write(*)", "WebFetch(*)", "Mcp(*:*)"], "deny": []}}
        return {"permissions": {"allow": [], "deny": []}}

    def sync_client_config(self, settings: dict) -> None:
        updates = self._build_client_config(settings)
        if not updates:
            return
        ensure_dir(self.config_dir)
        config_path = self.config_dir / "cli-config.json"
        existing: dict = {}
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        existing = deep_merge(existing, updates)
        write_content_if_different(
            config_path, json.dumps(existing, indent=2), backup=False
        )

    def get_oauth_src_path(self) -> Path | None:
        return None  # TBD

    def get_oauth_stash_filename(self) -> str | None:
        return None
