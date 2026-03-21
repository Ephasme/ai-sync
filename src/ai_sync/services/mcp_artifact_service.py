"""Service for collecting MCP artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ai_sync.data_classes.artifact import Artifact
from ai_sync.helpers import mcp_description, string_metadata_value
from ai_sync.models.env_dependency import EnvDependency

if TYPE_CHECKING:
    from ai_sync.clients.base import Client
    from ai_sync.data_classes.prepared_artifacts import PreparedArtifacts
    from ai_sync.data_classes.prepared_mcp_server import PreparedMcpServer
    from ai_sync.data_classes.resolved_source import ResolvedSource
    from ai_sync.data_classes.runtime_env import RuntimeEnv
    from ai_sync.models import ProjectManifest


def _resolve_servers_for_client(
    servers: dict[str, "PreparedMcpServer"], client_name: str
) -> dict[str, dict]:
    """Apply per-client overrides to each prepared MCP server's runtime config."""
    resolved: dict[str, dict] = {}
    for sid, prepared in servers.items():
        base = {k: v for k, v in prepared.runtime_config.items() if k != "client_overrides"}
        override = (prepared.runtime_config.get("client_overrides") or {}).get(client_name, {})
        if override:
            merged = {**base}
            for key, val in override.items():
                if val is None:
                    continue
                if key in ("headers", "auth") and isinstance(val, dict):
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


def _has_runtime_auth_data(server_config: dict) -> bool:
    for key in ("auth", "headers"):
        value = server_config.get(key)
        if isinstance(value, dict) and value:
            return True
    oauth = server_config.get("oauth")
    if isinstance(oauth, dict):
        secretish_fields = (
            "clientId",
            "clientSecret",
            "authorizationUrl",
            "tokenUrl",
            "issuer",
            "redirectUri",
            "scopes",
        )
        return any(oauth.get(field) for field in secretish_fields)
    return False


class McpArtifactService:
    """Build `Artifact` entries from the shared prepared MCP server context."""

    def collect_artifacts(
        self,
        *,
        project_root: Path,
        manifest: "ProjectManifest",
        resolved_sources: dict[str, "ResolvedSource"],
        runtime_env: "RuntimeEnv",
        prepared_artifacts: "PreparedArtifacts",
        clients: list["Client"],
    ) -> list[Artifact]:
        del project_root, resolved_sources, runtime_env

        servers_by_id: dict[str, PreparedMcpServer] = {
            entry.server_id: entry for entry in prepared_artifacts.mcp_servers
        }

        artifacts: list[Artifact] = []
        for client in clients:
            client_servers = _resolve_servers_for_client(servers_by_id, client.name)
            for prepared in prepared_artifacts.mcp_servers:
                server_config = client_servers.get(prepared.server_id)
                if server_config is None:
                    continue
                runtime_server_config = {
                    key: value
                    for key, value in server_config.items()
                    if key != "dependencies"
                }
                prefixed_id = f"{prepared.source_alias}-{prepared.server_id}"
                artifact_name = string_metadata_value(
                    runtime_server_config.get("name"), prepared.server_id
                )
                artifact_description = mcp_description(runtime_server_config)

                def make_resolve(
                    c: Client = client,
                    pid: str = prefixed_id,
                    srv: dict = runtime_server_config,
                ):
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

                has_secret_dependencies = any(
                    isinstance(dep, EnvDependency) and dep.mode == "secret"
                    for dep in prepared.env_dependencies.values()
                )
                has_secrets = has_secret_dependencies or _has_runtime_auth_data(
                    runtime_server_config
                )

                artifacts.append(
                    Artifact(
                        kind="mcp-server",
                        resource=prepared.scoped_ref,
                        name=artifact_name,
                        description=artifact_description,
                        source_alias=prepared.source_alias,
                        plan_key=plan_key,
                        secret_backed=has_secrets,
                        client=client.name,
                        resolve_fn=make_resolve(),
                        env_dependencies=prepared.env_dependencies,
                    )
                )
        return artifacts
