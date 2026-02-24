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

    def write_agent(self, slug: str, meta: dict, raw_content: str, prompt_src_path: Path, store: StateStore) -> None:
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
            ],
            store,
        )

    def write_command(self, slug: str, raw_content: str, command_src_path: Path, store: StateStore) -> None:
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
            ],
            store,
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
        oauth_cfg = server.get("oauth", {})
        if oauth_cfg.get("enabled") or oauth_cfg.get("authorizationUrl"):
            oauth_src = secret_srv.get("oauth") or secret_srv.get("auth") or server.get("oauth") or server.get("auth") or {}
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
                print(
                    f"  Warning: Invalid timeout_seconds for server '{server_id}': {server['timeout_seconds']!r}"
                )
        return entry

    def sync_mcp(self, servers: dict, secrets: dict, store: StateStore) -> None:
        gemini_mcp: dict = {}
        has_secrets = False
        for sid, srv in servers.items():
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
            track_write_blocks(specs, store)
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

    def sync_client_config(self, settings: dict, store: StateStore) -> None:
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
            track_write_blocks(specs, store)

    def post_apply(self) -> None:
        trusted_path = Path.home() / ".gemini" / "trustedFolders.json"
        project_key = str(self._project_root)
        data = self._read_json_config(trusted_path)

        if data.get(project_key) == "TRUST_FOLDER":
            return

        data[project_key] = "TRUST_FOLDER"
        trusted_path.parent.mkdir(parents=True, exist_ok=True)
        trusted_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def sync_instructions(self, instructions_content: str, store: StateStore) -> None:
        if not instructions_content.strip():
            return
        gemini_md = self.config_dir / "GEMINI.md"
        section = f"## Project Instructions (ai-sync)\n\n{instructions_content.strip()}\n"
        track_write_blocks(
            [
                WriteSpec(
                    file_path=gemini_md,
                    format="text",
                    target="ai-sync:instructions",
                    value=section,
                )
            ],
            store,
        )
