"""Service for collecting MCP artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ai_sync.data_classes.artifact import Artifact
from ai_sync.helpers import mcp_description, string_metadata_value
from ai_sync.models import split_scoped_ref

if TYPE_CHECKING:
    from ai_sync.clients.base import Client
    from ai_sync.data_classes.resolved_source import ResolvedSource
    from ai_sync.data_classes.runtime_env import RuntimeEnv
    from ai_sync.models import ProjectManifest
def _resolve_servers_for_client(servers: dict, client_name: str) -> dict:
    resolved = {}
    for sid, srv in servers.items():
        base = {k: v for k, v in srv.items() if k != "client_overrides"}
        override = (srv.get("client_overrides") or {}).get(client_name, {})
        if override:
            merged = {**base}
            for key, val in override.items():
                if val is None:
                    continue
                if key in ("env", "headers", "auth") and isinstance(val, dict):
                    merged[key] = {**(base.get(key) or {}), **val}
                elif key == "oauth" and isinstance(val, dict):
                    filtered_val = {k: v for k, v in val.items() if v is not None}
                    merged[key] = {**(base.get("oauth") or {}), **filtered_val}
                else:
                    merged[key] = val
            resolved[sid] = merged
        else:
            resolved[sid] = base
    return resolved


class McpArtifactService:
    """Build `Artifact` entries from the already prepared MCP manifest."""

    def collect_artifacts(
        self,
        *,
        project_root: Path,
        manifest: "ProjectManifest",
        resolved_sources: dict[str, "ResolvedSource"],
        runtime_env: "RuntimeEnv",
        mcp_manifest: dict,
        clients: list["Client"],
    ) -> list[Artifact]:
        del project_root, resolved_sources, runtime_env

        artifacts: list[Artifact] = []
        for client in clients:
            client_servers = _resolve_servers_for_client(mcp_manifest, client.name)
            for mcp_ref in manifest.mcp_servers:
                alias, server_id = split_scoped_ref(mcp_ref)
                server_config = client_servers.get(server_id)
                if server_config is None:
                    continue
                prefixed_id = f"{alias}-{server_id}"
                artifact_name = string_metadata_value(server_config.get("name"), server_id)
                artifact_description = mcp_description(server_config)

                def make_resolve(c: Client = client, pid: str = prefixed_id, srv: dict = server_config):
                    def resolve():
                        return c.build_mcp_specs({pid: srv}, {"servers": {}})

                    return resolve

                if client.name == "codex":
                    target_file = client.config_dir / "config.toml"
                    plan_key = f"{target_file}#/mcp_servers/{prefixed_id}"
                elif client.name == "claude":
                    target_file = client.config_dir.parent / ".mcp.json"
                    plan_key = f"{target_file}#/mcpServers/{prefixed_id}"
                else:
                    target_file = client.config_dir / (
                        "mcp.json" if client.name == "cursor" else "settings.json"
                    )
                    plan_key = f"{target_file}#/mcpServers/{prefixed_id}"

                has_secrets = bool(
                    server_config.get("env")
                    or server_config.get("auth")
                    or server_config.get("oauth")
                )

                artifacts.append(
                    Artifact(
                        kind="mcp-server",
                        resource=mcp_ref,
                        name=artifact_name,
                        description=artifact_description,
                        source_alias=alias,
                        plan_key=plan_key,
                        secret_backed=has_secrets,
                        client=client.name,
                        resolve_fn=make_resolve(),
                    )
                )
        return artifacts
