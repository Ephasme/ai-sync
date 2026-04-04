"""Claude Code client adapter."""

from __future__ import annotations

from pathlib import Path

from ai_sync.data_classes.write_spec import WriteSpec

from .base import Client


class ClaudeClient(Client):
    def __init__(self, project_root: Path) -> None:
        super().__init__(project_root)

    @property
    def name(self) -> str:
        return "claude"

    def build_agent_specs(
        self, alias: str, slug: str, meta: dict, raw_content: str, prompt_src_path: Path
    ) -> list[WriteSpec]:
        del prompt_src_path
        prefixed_slug = f"{alias}-{slug}"
        agent_path = self.get_agents_dir() / f"{prefixed_slug}.md"
        agent_name = str(meta.get("name", slug))
        description = str(meta.get("description", "AI Agent"))
        content = f"""---
name: {agent_name}
description: {description}
---

{raw_content}
"""
        return [
            WriteSpec(
                file_path=agent_path,
                format="text",
                target=f"ai-sync:agent:{prefixed_slug}",
                value=content,
            )
        ]

    def build_command_specs(
        self, alias: str, slug: str, meta: dict, raw_content: str, command_name: str
    ) -> list[WriteSpec]:
        rel = Path(command_name)
        target_path = self.config_dir / "commands" / rel.with_name(f"{alias}-{rel.name}.md")
        return [
            WriteSpec(
                file_path=target_path,
                format="text",
                target=f"ai-sync:command:{slug}",
                value=raw_content,
            )
        ]

    def _build_mcp_entry(self, server_id: str, server: dict, secrets: dict) -> dict:
        secret_srv = self._get_secret_for_server(server_id, secrets)
        method = server.get("method", "stdio")
        entry: dict = {}
        if method == "stdio":
            entry["type"] = "stdio"
            entry["command"] = server.get("command", "npx")
            entry["args"] = server.get("args", [])
        else:
            entry["type"] = method
            if url := server.get("url"):
                entry["url"] = url
            if server.get("headers"):
                entry["headers"] = server["headers"]

        env = self._build_mcp_env(server, secret_srv)
        if env:
            entry["env"] = env

        oauth_cfg = server.get("oauth", {})
        oauth_src = secret_srv.get("oauth") or secret_srv.get("auth") or server.get("auth") or {}
        oauth_entry: dict = {}
        for key in ("clientId", "clientSecret", "authorizationUrl", "tokenUrl", "issuer", "redirectUri"):
            val = oauth_cfg.get(key) or oauth_src.get(key)
            if val:
                oauth_entry[key] = str(val)
        scopes = oauth_cfg.get("scopes") or oauth_src.get("scopes")
        if isinstance(scopes, list) and scopes:
            oauth_entry["scopes"] = [str(s) for s in scopes]
        if oauth_entry:
            entry["oauth"] = oauth_entry

        return entry

    def build_mcp_specs(self, servers: dict, secrets: dict) -> list[WriteSpec]:
        mcp_path = self._project_root / ".mcp.json"
        return [
            WriteSpec(
                file_path=mcp_path,
                format="json",
                target=f"/mcpServers/{sid}",
                value=self._build_mcp_entry(sid, srv, secrets),
            )
            for sid, srv in servers.items()
        ]

    def _build_client_config(self, settings: dict) -> dict:
        mode = settings.get("mode") or "normal"
        if mode in {"normal", "yolo"}:
            return {
                "$schema": "https://json.schemastore.org/claude-code-settings.json",
                "permissions": {"allow": ["Bash(*)"], "deny": []},
            }
        return {
            "$schema": "https://json.schemastore.org/claude-code-settings.json",
            "permissions": {"allow": [], "deny": []},
        }

    def build_client_config_specs(self, settings: dict) -> list[WriteSpec]:
        updates = self._build_client_config(settings)
        settings_path = self.config_dir / "settings.json"
        return [
            WriteSpec(
                file_path=settings_path,
                format="json",
                target="/$schema",
                value=updates["$schema"],
            ),
            WriteSpec(
                file_path=settings_path,
                format="json",
                target="/permissions/allow",
                value=updates["permissions"]["allow"],
            ),
            WriteSpec(
                file_path=settings_path,
                format="json",
                target="/permissions/deny",
                value=updates["permissions"]["deny"],
            ),
        ]

    def build_instructions_specs(self, instructions_content: str) -> list[WriteSpec]:
        if not instructions_content.strip():
            return []
        agents_md = self._project_root / "AGENTS.md"
        section = f"## Project Instructions (ai-sync)\n\n{instructions_content.strip()}\n"
        return [
            WriteSpec(
                file_path=agents_md,
                format="text",
                target="ai-sync:instructions",
                value=section,
            )
        ]
