"""Gemini CLI client adapter."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

from ai_sync.helpers import (
    deep_merge,
    ensure_dir,
    write_content_if_different,
)

from .base import Client


class GeminiClient(Client):
    @property
    def name(self) -> str:
        return "gemini"

    @property
    def config_dir(self) -> Path:
        return Path.home() / ".gemini"

    def write_agent(self, slug: str, meta: dict, raw_content: str, prompt_src_path: Path) -> None:
        ensure_dir(self.get_agents_dir())
        agent_path = self.get_agents_dir() / f"{slug}.md"
        content = f"""---
name: {slug}
description: {json.dumps(meta.get("description", "AI Agent"))}
model: auto
tools: {json.dumps(meta.get("tools", ["google_web_search"]))}
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
        if method in ("http", "sse"):
            if server.get("url"):
                entry["url"] = server["url"]
            if server.get("httpUrl"):
                entry["httpUrl"] = server["httpUrl"]
        if server.get("trust") is True:
            entry["trust"] = True
        if server.get("description"):
            entry["description"] = str(server["description"])
        if server.get("oauth", {}).get("enabled"):
            oauth_src = secret_srv.get("oauth") or secret_srv.get("auth") or server.get("oauth") or server.get("auth") or {}
            oauth_cfg = server.get("oauth", {})
            client_id = (oauth_src.get("clientId") or "").strip()
            client_secret = (oauth_src.get("clientSecret") or "").strip()
            scopes = oauth_cfg.get("scopes") or oauth_src.get("scopes") or []
            if client_id:
                entry["oauth"] = {"enabled": True, "clientId": client_id, "clientSecret": client_secret}
                if scopes:
                    entry["oauth"]["scopes"] = [str(s) for s in scopes]
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
        gemini_mcp: dict = {}
        has_secrets = False
        for sid, srv in servers.items():
            if not for_client(srv, self.name):
                continue
            entry = self._build_mcp_entry(sid, srv, secrets)
            gemini_mcp[sid] = entry
            if entry.get("env") or entry.get("oauth"):
                has_secrets = True
        ensure_dir(self.config_dir)
        settings_path = self.config_dir / "settings.json"
        existing = self._read_json_config(settings_path)
        existing["mcpServers"] = self._merge_managed_servers(existing.get("mcpServers", {}), gemini_mcp)
        write_content_if_different(settings_path, self._write_json_config(existing))
        if has_secrets:
            self._set_restrictive_permissions(settings_path)
            self._warn_plaintext_secrets(settings_path)

    def _build_client_config(self, settings: dict) -> dict:
        out: dict = {}
        mode = settings.get("mode") or "normal"
        if settings.get("experimental") or mode == "strict":
            out.setdefault("experimental", {})
            out["experimental"]["plan"] = True
        if settings.get("subagents", True):
            out.setdefault("experimental", {})
            out["experimental"]["enableAgents"] = True
        mode_map = {"strict": "plan", "normal": "auto_edit", "yolo": "yolo"}
        out.setdefault("general", {})
        out["general"]["defaultApprovalMode"] = mode_map.get(mode, "default")
        tools = settings.get("tools")
        sandbox_override = None
        if mode == "strict":
            sandbox_override = True
        elif mode in {"normal", "yolo"}:
            sandbox_override = False
        if sandbox_override is not None:
            out.setdefault("tools", {})
            out["tools"]["sandbox"] = sandbox_override
        elif isinstance(tools, dict) and "sandbox" in tools:
            out.setdefault("tools", {})
            out["tools"]["sandbox"] = bool(tools["sandbox"])
        return out

    def sync_client_config(self, settings: dict) -> None:
        updates = self._build_client_config(settings)
        if not updates:
            return
        ensure_dir(self.config_dir)
        settings_path = self.config_dir / "settings.json"
        existing = self._read_json_config(settings_path)
        write_content_if_different(settings_path, self._write_json_config(deep_merge(existing, updates)))

    def sync_mcp_instructions(self, instructions: str) -> None:
        if not instructions or not instructions.strip():
            return
        ensure_dir(self.config_dir)
        gemini_md = self.config_dir / "GEMINI.md"
        begin_marker = "<!-- BEGIN ai-sync MCP instructions -->"
        end_marker = "<!-- END ai-sync MCP instructions -->"
        section = f"\n\n## MCP Server Instructions (ai-sync)\n\n{instructions.strip()}\n"
        block = f"{begin_marker}\n{section.strip()}\n{end_marker}"
        if gemini_md.exists():
            content = gemini_md.read_text(encoding="utf-8")
            pattern = re.compile(rf"{re.escape(begin_marker)}.*?{re.escape(end_marker)}", re.DOTALL)
            new_content = pattern.sub(block, content) if pattern.search(content) else content.rstrip() + "\n\n" + block + "\n"
        else:
            new_content = block + "\n"
        write_content_if_different(gemini_md, new_content)

    def enable_subagents_fallback(self) -> None:
        settings_path = self.config_dir / "settings.json"
        if not settings_path.exists():
            return
        data = self._read_json_config(settings_path)
        changed = False
        if "experimental" not in data:
            data["experimental"] = {}
            changed = True
        if not data["experimental"].get("enableAgents"):
            data["experimental"]["enableAgents"] = True
            changed = True
        if changed:
            print("  Enabling experimental.enableAgents in ~/.gemini/settings.json")
            write_content_if_different(settings_path, self._write_json_config(data))
