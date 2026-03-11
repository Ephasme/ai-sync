"""Codex client adapter."""

from __future__ import annotations

from pathlib import Path

from ai_sync.track_write import WriteSpec

from .base import Client


class CodexClient(Client):
    def __init__(self, project_root: Path) -> None:
        super().__init__(project_root)

    @property
    def name(self) -> str:
        return "codex"

    def build_agent_specs(
        self, alias: str, slug: str, meta: dict, raw_content: str, prompt_src_path: Path
    ) -> list[WriteSpec]:
        prefixed_slug = f"{alias}-{slug}"
        agent_dir = self.get_agents_dir() / prefixed_slug
        codex_prompt_path = agent_dir / "prompt.md"
        return [
            WriteSpec(
                file_path=codex_prompt_path,
                format="text",
                target=f"ai-sync:agent:{prefixed_slug}:prompt",
                value=raw_content,
            ),
            WriteSpec(
                file_path=agent_dir / "config.toml",
                format="toml",
                target="/model",
                value="auto",
            ),
            WriteSpec(
                file_path=agent_dir / "config.toml",
                format="toml",
                target="/model_reasoning_effort",
                value=meta.get("reasoning_effort", "high"),
            ),
            WriteSpec(
                file_path=agent_dir / "config.toml",
                format="toml",
                target="/model_instructions_file",
                value=str(codex_prompt_path),
            ),
            WriteSpec(
                file_path=agent_dir / "config.toml",
                format="toml",
                target="/web_search",
                value="live" if meta.get("web_search", True) else "off",
            ),
        ]

    def build_command_specs(
        self, alias: str, slug: str, raw_content: str, command_src_path: Path
    ) -> list[WriteSpec]:
        if command_src_path.suffix == ".mdc":
            target_dir = self.config_dir / "rules"
        else:
            target_dir = self.config_dir / "commands"
        prefixed = command_src_path.with_name(f"{alias}-{command_src_path.name}")
        target_path = target_dir / prefixed
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
        table: dict = {}
        if server.get("method") in ("http", "sse"):
            table["url"] = server.get("url", "")
            if server.get("headers"):
                table["http_headers"] = server["headers"]
        else:
            table["command"] = server.get("command", "npx")
            table["args"] = server.get("args", [])
            env = self._build_mcp_env(server, secret_srv)
            if env:
                table["env"] = env
        if server.get("description"):
            table["description"] = str(server["description"])
        oauth_cfg = server.get("oauth", {})
        if oauth_cfg.get("enabled") or oauth_cfg.get("authorizationUrl"):
            oauth_src = (
                secret_srv.get("oauth") or secret_srv.get("auth") or server.get("oauth") or server.get("auth") or {}
            )
            oauth_entry: dict = {}
            if oauth_cfg.get("enabled"):
                oauth_entry["enabled"] = True
            for key in ("authorizationUrl", "tokenUrl", "issuer", "redirectUri"):
                val = oauth_cfg.get(key) or oauth_src.get(key)
                if val:
                    oauth_entry[key] = str(val)
            if oauth_entry:
                table["oauth"] = oauth_entry
        if "timeout_seconds" in server and server.get("timeout_seconds") is not None:
            try:
                sec = float(server["timeout_seconds"])
                if sec < 0:
                    raise ValueError
                sec_value = int(sec) if sec.is_integer() else sec
                table["startup_timeout_sec"] = sec_value
                table["tool_timeout_sec"] = sec_value
            except (TypeError, ValueError):
                print(f"  Warning: Invalid timeout_seconds for server '{server_id}': {server['timeout_seconds']!r}")
        return table

    def build_mcp_specs(self, servers: dict, secrets: dict) -> list[WriteSpec]:
        config_path = self.config_dir / "config.toml"
        return [
            WriteSpec(
                file_path=config_path,
                format="toml",
                target=f"/mcp_servers/{sid}",
                value=self._build_mcp_entry(sid, srv, secrets),
            )
            for sid, srv in servers.items()
        ]

    def _build_client_config(self, settings: dict) -> dict:
        out: dict = {}
        if settings.get("experimental"):
            out["suppress_unstable_features_warning"] = True
        if settings.get("subagents", True):
            out.setdefault("features", {})
            out["features"]["multi_agent"] = True
            out["features"]["child_agents_md"] = True
        mode = settings.get("mode") or "normal"
        if mode == "yolo":
            out["approval_policy"] = "never"
            out["sandbox_mode"] = "danger-full-access"
        elif mode == "normal":
            out["approval_policy"] = "untrusted"
            out["sandbox_mode"] = "danger-full-access"
        elif mode == "strict":
            out["approval_policy"] = "on-request"
            out["sandbox_mode"] = "read-only"
        else:
            out["approval_policy"] = "on-request"
            out["sandbox_mode"] = "workspace-write"
        return out

    def build_client_config_specs(self, settings: dict) -> list[WriteSpec]:
        updates = self._build_client_config(settings)
        if not updates:
            return []
        config_path = self.config_dir / "config.toml"
        specs = []
        if "suppress_unstable_features_warning" in updates:
            specs.append(
                WriteSpec(
                    file_path=config_path,
                    format="toml",
                    target="/suppress_unstable_features_warning",
                    value=updates["suppress_unstable_features_warning"],
                )
            )
        if "features" in updates:
            features = updates["features"] or {}
            if "multi_agent" in features:
                specs.append(
                    WriteSpec(
                        file_path=config_path,
                        format="toml",
                        target="/features/multi_agent",
                        value=features["multi_agent"],
                    )
                )
            if "child_agents_md" in features:
                specs.append(
                    WriteSpec(
                        file_path=config_path,
                        format="toml",
                        target="/features/child_agents_md",
                        value=features["child_agents_md"],
                    )
                )
        if "approval_policy" in updates:
            specs.append(
                WriteSpec(
                    file_path=config_path,
                    format="toml",
                    target="/approval_policy",
                    value=updates["approval_policy"],
                )
            )
        if "sandbox_mode" in updates:
            specs.append(
                WriteSpec(
                    file_path=config_path,
                    format="toml",
                    target="/sandbox_mode",
                    value=updates["sandbox_mode"],
                )
            )
        return specs

    def build_instructions_specs(self, instructions_content: str) -> list[WriteSpec]:
        if not instructions_content.strip():
            return []
        config_path = self.config_dir / "config.toml"
        return [
            WriteSpec(
                file_path=config_path,
                format="toml",
                target="/developer_instructions",
                value=instructions_content.strip(),
            )
        ]
