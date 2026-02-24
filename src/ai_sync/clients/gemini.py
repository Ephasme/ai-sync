"""Gemini CLI client adapter."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from ai_sync.state_store import StateStore
from ai_sync.track_write import DELETE, WriteSpec, track_write_blocks

from .base import Client


class GeminiClient(Client):
    @property
    def name(self) -> str:
        return "gemini"

    @property
    def config_dir(self) -> Path:
        return Path.home() / ".gemini"

    def write_agent(self, slug: str, meta: dict, raw_content: str, prompt_src_path: Path) -> None:
        agent_path = self.get_agents_dir() / f"{slug}.md"
        content = f"""---
name: {slug}
description: {json.dumps(meta.get("description", "AI Agent"))}
model: auto
tools: {json.dumps(meta.get("tools", ["google_web_search"]))}
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
        settings_path = self.config_dir / "settings.json"
        specs: list[WriteSpec] = [
            WriteSpec(
                file_path=settings_path,
                format="json",
                target=f"/mcpServers/{sid}",
                value=entry,
            )
            for sid, entry in gemini_mcp.items()
        ]
        store = StateStore()
        store.load()
        existing_targets = store.list_targets(settings_path, "json", "/mcpServers/")
        existing_ids = {t.split("/", 2)[2] for t in existing_targets if t.count("/") >= 2}
        for sid in sorted(existing_ids - set(gemini_mcp.keys())):
            specs.append(
                WriteSpec(
                    file_path=settings_path,
                    format="json",
                    target=f"/mcpServers/{sid}",
                    value=DELETE,
                )
            )
        if specs:
            track_write_blocks(specs)
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
        settings_path = self.config_dir / "settings.json"
        specs: list[WriteSpec] = []
        experimental = updates.get("experimental", {}) or {}
        if "plan" in experimental:
            specs.append(
                WriteSpec(
                    file_path=settings_path,
                    format="json",
                    target="/experimental/plan",
                    value=experimental["plan"],
                )
            )
        if "enableAgents" in experimental:
            specs.append(
                WriteSpec(
                    file_path=settings_path,
                    format="json",
                    target="/experimental/enableAgents",
                    value=experimental["enableAgents"],
                )
            )
        general = updates.get("general", {}) or {}
        if "defaultApprovalMode" in general:
            specs.append(
                WriteSpec(
                    file_path=settings_path,
                    format="json",
                    target="/general/defaultApprovalMode",
                    value=general["defaultApprovalMode"],
                )
            )
        tools = updates.get("tools", {}) or {}
        if "sandbox" in tools:
            specs.append(
                WriteSpec(
                    file_path=settings_path,
                    format="json",
                    target="/tools/sandbox",
                    value=tools["sandbox"],
                )
            )
        if specs:
            track_write_blocks(specs)

    def sync_mcp_instructions(self, instructions: str) -> None:
        if not instructions or not instructions.strip():
            return
        gemini_md = self.config_dir / "GEMINI.md"
        section = f"## MCP Server Instructions (ai-sync)\n\n{instructions.strip()}\n"
        track_write_blocks(
            [
                WriteSpec(
                    file_path=gemini_md,
                    format="text",
                    target="ai-sync:mcp-instructions",
                    value=section,
                )
            ]
        )

    def enable_subagents_fallback(self) -> None:
        settings_path = self.config_dir / "settings.json"
        if not settings_path.exists():
            return
        track_write_blocks(
            [
                WriteSpec(
                    file_path=settings_path,
                    format="json",
                    target="/experimental/enableAgents",
                    value=True,
                )
            ]
        )
