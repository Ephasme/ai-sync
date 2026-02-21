"""Gemini CLI client adapter."""
import json
from pathlib import Path

from .base import Client
from helpers import deep_merge, ensure_dir, write_content_if_different


class GeminiClient(Client):
    @property
    def name(self) -> str:
        return "gemini"

    @property
    def config_dir(self) -> Path:
        return Path.home() / ".gemini"

    def write_agent(
        self,
        slug: str,
        meta: dict,
        raw_content: str,
        prompt_src_path: Path,
    ) -> None:
        ensure_dir(self.get_agents_dir())
        agent_path = self.get_agents_dir() / f"{slug}.md"
        description = meta.get("description", "AI Agent")
        gemini_model = meta.get("models", {}).get("gemini", "gemini-2.0-flash-thinking-exp")
        tools_list = json.dumps(meta.get("tools", ["google_web_search"]))
        content = f"""---
name: {slug}
description: {json.dumps(description)}
model: {gemini_model}
tools: {tools_list}
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
        if server.get("method") in ("http", "sse"):
            entry["url"] = server.get("url", "")
            if "httpUrl" in server:
                entry["httpUrl"] = server["httpUrl"]
        return entry

    def sync_mcp(self, servers: dict, secrets: dict, for_client) -> None:
        gemini_mcp: dict = {}
        for sid, srv in servers.items():
            if not for_client(srv, self.name):
                continue
            gemini_mcp[sid] = self._build_mcp_entry(sid, srv, secrets)
        if not gemini_mcp:
            return
        ensure_dir(self.config_dir)
        settings_path = self.config_dir / "settings.json"
        existing: dict = {}
        if settings_path.exists():
            try:
                with open(settings_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        if "mcpServers" not in existing:
            existing["mcpServers"] = {}
        existing["mcpServers"] = deep_merge(
            dict(existing["mcpServers"]),
            gemini_mcp,
        )
        write_content_if_different(
            settings_path, json.dumps(existing, indent=2), backup=False
        )

    def _build_client_config(self, settings: dict) -> dict:
        out: dict = {}
        subagents = settings.get("subagents", True)
        mode = settings.get("mode", "ask")

        if subagents:
            out.setdefault("experimental", {})
            out["experimental"]["enableAgents"] = True

        mode_map = {"ask": "default", "ask-once": "auto_edit", "full-access": "yolo"}
        out.setdefault("general", {})
        out["general"]["defaultApprovalMode"] = mode_map.get(mode, "default")
        return out

    def sync_client_config(self, settings: dict) -> None:
        updates = self._build_client_config(settings)
        if not updates:
            return
        ensure_dir(self.config_dir)
        settings_path = self.config_dir / "settings.json"
        existing: dict = {}
        if settings_path.exists():
            try:
                with open(settings_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        existing = deep_merge(existing, updates)
        write_content_if_different(
            settings_path, json.dumps(existing, indent=2), backup=False
        )

    def get_oauth_src_path(self) -> Path | None:
        return self.config_dir / "mcp-oauth-tokens.json"

    def get_oauth_stash_filename(self) -> str | None:
        return "gemini-mcp-oauth-tokens.json"

    def enable_subagents_fallback(self) -> None:
        """Enable experimental subagents when config/client-settings/settings.yaml is absent. Fallback only."""
        settings_path = self.config_dir / "settings.json"
        if not settings_path.exists():
            return
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            changed = False
            if "experimental" not in data:
                data["experimental"] = {}
                changed = True
            if not data["experimental"].get("enableAgents"):
                data["experimental"]["enableAgents"] = True
                changed = True
            if changed:
                print("  Enabling experimental.enableAgents in ~/.gemini/settings.json")
                with open(settings_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
        except (json.JSONDecodeError, OSError) as e:
            print(f"  Warning: Could not update Gemini settings: {e}")
