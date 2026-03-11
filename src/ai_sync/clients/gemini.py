"""Gemini CLI client adapter."""

from __future__ import annotations

import json
from pathlib import Path

from ai_sync.state_store import StateStore
from ai_sync.track_write import DELETE, WriteSpec, track_write_blocks

from .base import Client


class GeminiClient(Client):
    def __init__(self, project_root: Path) -> None:
        super().__init__(project_root)

    @property
    def name(self) -> str:
        return "gemini"

    def build_agent_specs(self, slug: str, meta: dict, raw_content: str, prompt_src_path: Path) -> list[WriteSpec]:
        agent_path = self.get_agents_dir() / f"{slug}.md"
        content = f"""---
name: {slug}
description: {json.dumps(meta.get("description", "AI Agent"))}
model: auto
tools: {json.dumps(meta.get("tools", ["google_web_search"]))}
---

{raw_content}
"""
        return [
            WriteSpec(
                file_path=agent_path,
                format="text",
                target=f"ai-sync:agent:{slug}",
                value=content,
            )
        ]

    def write_agent(self, slug: str, meta: dict, raw_content: str, prompt_src_path: Path, store: StateStore) -> None:
        track_write_blocks(self.build_agent_specs(slug, meta, raw_content, prompt_src_path), store)

    def build_command_specs(self, slug: str, raw_content: str, command_src_path: Path) -> list[WriteSpec]:
        if command_src_path.suffix == ".mdc":
            target_dir = self.config_dir / "rules"
        else:
            target_dir = self.config_dir / "commands"
        target_path = target_dir / command_src_path
        return [
            WriteSpec(
                file_path=target_path,
                format="text",
                target=f"ai-sync:command:{slug}",
                value=raw_content,
            )
        ]

    def write_command(self, slug: str, raw_content: str, command_src_path: Path, store: StateStore) -> None:
        track_write_blocks(self.build_command_specs(slug, raw_content, command_src_path), store)

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
            if url := server.get("url"):
                entry["url"] = url
            if server.get("headers"):
                entry["headers"] = server["headers"]
        if server.get("auth_provider_type"):
            entry["authProviderType"] = str(server["auth_provider_type"])
        if server.get("trust") is True:
            entry["trust"] = True
        if server.get("description"):
            entry["description"] = str(server["description"])
        oauth_cfg = server.get("oauth", {})
        if oauth_cfg.get("enabled") or oauth_cfg.get("authorizationUrl") or oauth_cfg.get("scopes"):
            oauth_src = (
                secret_srv.get("oauth") or secret_srv.get("auth") or server.get("oauth") or server.get("auth") or {}
            )
            client_id = (oauth_src.get("clientId") or "").strip()
            client_secret = (oauth_src.get("clientSecret") or "").strip()
            scopes = oauth_cfg.get("scopes") or oauth_src.get("scopes") or []
            oauth_entry: dict = {}
            if oauth_cfg.get("enabled"):
                oauth_entry["enabled"] = True
            if client_id:
                oauth_entry["clientId"] = client_id
                oauth_entry["clientSecret"] = client_secret
            for key in ("authorizationUrl", "tokenUrl", "issuer", "redirectUri"):
                val = oauth_cfg.get(key) or oauth_src.get(key)
                if val:
                    oauth_entry[key] = str(val)
            if scopes:
                oauth_entry["scopes"] = [str(s) for s in scopes]
            entry["oauth"] = oauth_entry
        if "timeout_seconds" in server and server.get("timeout_seconds") is not None:
            try:
                sec = float(server["timeout_seconds"])
                if sec < 0:
                    raise ValueError
                entry["timeout"] = int(sec * 1000)
            except (TypeError, ValueError):
                print(f"  Warning: Invalid timeout_seconds for server '{server_id}': {server['timeout_seconds']!r}")
        return entry

    def build_mcp_specs(self, servers: dict, secrets: dict) -> list[WriteSpec]:
        gemini_mcp: dict = {}
        for sid, srv in servers.items():
            entry = self._build_mcp_entry(sid, srv, secrets)
            gemini_mcp[sid] = entry
        settings_path = self.config_dir / "settings.json"
        return [
            WriteSpec(
                file_path=settings_path,
                format="json",
                target=f"/mcpServers/{sid}",
                value=entry,
            )
            for sid, entry in gemini_mcp.items()
        ]

    def sync_mcp(self, servers: dict, secrets: dict, store: StateStore) -> None:
        settings_path = self.config_dir / "settings.json"
        specs = self.build_mcp_specs(servers, secrets)
        existing_targets = store.list_targets(settings_path, "json", "/mcpServers/")
        desired_targets = {spec.target for spec in specs if spec.target.startswith("/mcpServers/")}
        existing_ids = {t.split("/", 2)[2] for t in existing_targets if t.count("/") >= 2}
        desired_ids = {t.split("/", 2)[2] for t in desired_targets if t.count("/") >= 2}
        for sid in sorted(existing_ids - desired_ids):
            specs.append(
                WriteSpec(
                    file_path=settings_path,
                    format="json",
                    target=f"/mcpServers/{sid}",
                    value=DELETE,
                )
            )
        if specs:
            track_write_blocks(specs, store)
        gemini_mcp = {
            spec.target.split("/", 2)[2]: spec.value
            for spec in specs
            if spec.target.startswith("/mcpServers/") and spec.value is not DELETE
        }
        has_secrets = any(
            isinstance(entry, dict) and (entry.get("env") or entry.get("oauth"))
            for entry in gemini_mcp.values()
        )
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
        mode_map = {"strict": "plan", "normal": "auto_edit", "yolo": "auto_edit"}
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

    def build_client_config_specs(self, settings: dict) -> list[WriteSpec]:
        updates = self._build_client_config(settings)
        if not updates:
            return []
        settings_path = self.config_dir / "settings.json"
        specs = []
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
        tools_cfg = updates.get("tools", {}) or {}
        if "sandbox" in tools_cfg:
            specs.append(
                WriteSpec(
                    file_path=settings_path,
                    format="json",
                    target="/tools/sandbox",
                    value=tools_cfg["sandbox"],
                )
            )
        if specs:
            return specs
        return []

    def sync_client_config(self, settings: dict, store: StateStore) -> None:
        specs = self.build_client_config_specs(settings)
        if specs:
            track_write_blocks(specs, store)

    def post_apply(self) -> None:
        return

    def build_instructions_specs(self, instructions_content: str) -> list[WriteSpec]:
        if not instructions_content.strip():
            return []
        gemini_md = self.config_dir / "GEMINI.md"
        section = f"## Project Instructions (ai-sync)\n\n{instructions_content.strip()}\n"
        return [
            WriteSpec(
                file_path=gemini_md,
                format="text",
                target="ai-sync:instructions",
                value=section,
            )
        ]

    def sync_instructions(self, instructions_content: str, store: StateStore) -> None:
        specs = self.build_instructions_specs(instructions_content)
        if specs:
            track_write_blocks(specs, store)
