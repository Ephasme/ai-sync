"""Codex client adapter."""

from __future__ import annotations

import shlex
from pathlib import Path

import tomli
import tomli_w

from ai_sync.state_store import StateStore
from ai_sync.track_write import DELETE, WriteSpec, track_write_blocks

from .base import Client


class CodexClient(Client):
    def __init__(self, project_root: Path) -> None:
        super().__init__(project_root)

    @property
    def name(self) -> str:
        return "codex"

    def write_agent(self, slug: str, meta: dict, raw_content: str, prompt_src_path: Path, store: StateStore) -> None:
        agent_dir = self.get_agents_dir() / slug
        codex_prompt_path = agent_dir / "prompt.md"
        specs = [
            WriteSpec(
                file_path=codex_prompt_path,
                format="text",
                target=f"ai-sync:agent:{slug}:prompt",
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
        track_write_blocks(specs, store)

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
        table: dict = {}
        if server.get("method") in ("http", "sse"):
            table["url"] = server.get("url") or server.get("httpUrl", "")
            if server.get("bearer_token_env_var"):
                table["bearer_token_env_var"] = server["bearer_token_env_var"]
        else:
            table["command"] = server.get("command", "npx")
            table["args"] = server.get("args", [])
            env = self._build_mcp_env(server, secret_srv)
            if env:
                table["env"] = env
        if server.get("description"):
            table["description"] = str(server["description"])
        if "timeout_seconds" in server and server.get("timeout_seconds") is not None:
            try:
                sec = float(server["timeout_seconds"])
                if sec < 0:
                    raise ValueError
                sec_value = int(sec) if sec.is_integer() else sec
                table["startup_timeout_sec"] = sec_value
                table["tool_timeout_sec"] = sec_value
            except (TypeError, ValueError):
                print(
                    f"  Warning: Invalid timeout_seconds for server '{server_id}': {server['timeout_seconds']!r}"
                )
        return table

    def sync_mcp(self, servers: dict, secrets: dict, store: StateStore) -> None:
        codex_mcp: dict = {}
        bearer_exports: list[str] = []
        for sid, srv in servers.items():
            entry = self._build_mcp_entry(sid, srv, secrets)
            codex_mcp[sid] = entry
            var_name = srv.get("bearer_token_env_var")
            if var_name:
                val = (srv.get("env", {}).get(var_name) or "")
                if val:
                    bearer_exports.append(f"export {var_name}={shlex.quote(val)}")

        config_path = self.config_dir / "config.toml"
        specs: list[WriteSpec] = [
            WriteSpec(
                file_path=config_path,
                format="toml",
                target=f"/mcp_servers/{sid}",
                value=entry,
            )
            for sid, entry in codex_mcp.items()
        ]
        existing_targets = store.list_targets(config_path, "toml", "/mcp_servers/")
        existing_ids = {t.split("/", 2)[2] for t in existing_targets if t.count("/") >= 2}
        for sid in sorted(existing_ids - set(codex_mcp.keys())):
            specs.append(
                WriteSpec(
                    file_path=config_path,
                    format="toml",
                    target=f"/mcp_servers/{sid}",
                    value=DELETE,
                )
            )
        if specs:
            track_write_blocks(specs, store)
        if any(e.get("env") for e in codex_mcp.values()):
            self._set_restrictive_permissions(config_path)
            self._warn_plaintext_secrets(config_path)

        mcp_env_path = self.config_dir / "mcp.env"
        if bearer_exports:
            content = "# Generated by ai-sync. Source .codex/mcp.env before running Codex.\n" + "\n".join(bearer_exports) + "\n"
            track_write_blocks(
                [
                    WriteSpec(
                        file_path=mcp_env_path,
                        format="text",
                        target="ai-sync:codex-mcp-env",
                        value=content,
                    )
                ],
                store,
            )
            self._set_restrictive_permissions(mcp_env_path)
            self._warn_plaintext_secrets(mcp_env_path)
        else:
            track_write_blocks(
                [
                    WriteSpec(
                        file_path=mcp_env_path,
                        format="text",
                        target="ai-sync:codex-mcp-env",
                        value=DELETE,
                    )
                ],
                store,
            )
            if mcp_env_path.exists() and not mcp_env_path.read_text(encoding="utf-8").strip():
                mcp_env_path.unlink(missing_ok=True)

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

    def sync_client_config(self, settings: dict, store: StateStore) -> None:
        updates = self._build_client_config(settings)
        if not updates:
            return
        config_path = self.config_dir / "config.toml"
        specs: list[WriteSpec] = []
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
        if specs:
            track_write_blocks(specs, store)

    def sync_instructions(self, instructions_content: str, store: StateStore) -> None:
        if not instructions_content.strip():
            return
        config_path = self.config_dir / "config.toml"
        track_write_blocks(
            [
                WriteSpec(
                    file_path=config_path,
                    format="toml",
                    target="/developer_instructions",
                    value=instructions_content.strip(),
                )
            ],
            store,
        )

    def post_apply(self) -> None:
        global_config_path = Path.home() / ".codex" / "config.toml"
        project_key = str(self._project_root)
        data: dict = {}
        if global_config_path.exists():
            try:
                with open(global_config_path, "rb") as f:
                    data = tomli.load(f)
            except (OSError, tomli.TOMLDecodeError):
                data = {}

        projects = data.get("projects", {})
        if not isinstance(projects, dict):
            projects = {}
        if projects.get(project_key, {}).get("trust_level") == "trusted":
            return

        projects[project_key] = {"trust_level": "trusted"}
        data["projects"] = projects
        global_config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(global_config_path, "wb") as f:
            tomli_w.dump(data, f)
