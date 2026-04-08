"""Cursor client adapter."""

from __future__ import annotations

from pathlib import Path

from ai_sync.data_classes.write_spec import WriteSpec

from .base import Client


class CursorClient(Client):
    def __init__(self, project_root: Path) -> None:
        super().__init__(project_root)

    @property
    def name(self) -> str:
        return "cursor"

    def build_agent_specs(
        self, alias: str, slug: str, meta: dict, raw_content: str, prompt_src_path: Path
    ) -> list[WriteSpec]:
        prefixed_slug = f"{alias}-{slug}"
        agent_path = self.get_agents_dir() / f"{prefixed_slug}.md"
        content = f"""---
name: {meta.get("name", slug)}
description: {meta.get("description", "AI Agent")}
model: auto
is_background: {"true" if meta.get("is_background", False) else "false"}
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
        entry: dict = {"disabled": False}
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
            if url := server.get("url"):
                entry["url"] = url
            if server.get("headers"):
                entry["headers"] = server["headers"]
        if server.get("trust") is True:
            entry["trust"] = True
        if server.get("description"):
            entry["description"] = str(server["description"])
        oauth_cfg = server.get("oauth", {})
        if oauth_cfg.get("enabled") or oauth_cfg.get("authorizationUrl") or oauth_cfg.get("scopes"):
            oauth_src = (
                secret_srv.get("oauth") or secret_srv.get("auth") or server.get("oauth") or server.get("auth") or {}
            )
            oauth_entry: dict = {}
            if oauth_cfg.get("enabled"):
                oauth_entry["enabled"] = True
            client_id = (oauth_cfg.get("clientId") or oauth_src.get("clientId") or "").strip()
            client_secret = (oauth_cfg.get("clientSecret") or oauth_src.get("clientSecret") or "").strip()
            if client_id:
                oauth_entry["clientId"] = client_id
                oauth_entry["clientSecret"] = client_secret
            for key in ("authorizationUrl", "tokenUrl", "issuer", "redirectUri"):
                val = oauth_cfg.get(key) or oauth_src.get(key)
                if val:
                    oauth_entry[key] = str(val)
            scopes = oauth_cfg.get("scopes") or oauth_src.get("scopes")
            if isinstance(scopes, list) and scopes:
                oauth_entry["scopes"] = [str(s) for s in scopes]
            if oauth_entry:
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
        mcp_path = self.config_dir / "mcp.json"
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
                "permissions": {
                    "allow": ["Shell(*)", "Read(*)", "Write(*)", "WebFetch(*)", "Mcp(*:*)"],
                    "deny": [],
                }
            }
        return {"permissions": {"allow": [], "deny": []}}

    def build_client_config_specs(self, settings: dict) -> list[WriteSpec]:
        updates = self._build_client_config(settings)
        if not updates:
            return []
        config_path = self.config_dir / "cli-config.json"
        permissions = updates.get("permissions", {})
        return [
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

    def build_instructions_specs(self, instructions_content: str) -> list[WriteSpec]:
        if not instructions_content.strip():
            return []
        rules_dir = self.config_dir / "rules"
        content = f"""---
description: Project instructions managed by ai-sync
alwaysApply: true
---

{instructions_content.strip()}
"""
        return [
            WriteSpec(
                file_path=rules_dir / "instructions.mdc",
                format="text",
                target="ai-sync:instructions",
                value=content,
            )
        ]
