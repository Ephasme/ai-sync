"""Manifest loading and validation."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

import yaml
from pydantic import ValidationError

from .display import Display
from .models import MCPManifest, ServerConfig
from .project import split_scoped_ref
from .source_resolver import ResolvedSource


def load_manifest(mcp_root: Path, display: Display) -> dict:
    servers_dir = mcp_root / "mcp-servers"
    if not servers_dir.exists():
        return {}

    servers: dict[str, dict] = {}
    for server_dir in sorted(servers_dir.iterdir()):
        if not server_dir.is_dir():
            continue
        config_path = server_dir / "artifact.yaml"
        if not config_path.exists():
            display.print(
                f"Skipping malformed MCP server directory without artifact.yaml: {server_dir}",
                style="warning",
            )
            continue
        servers[server_dir.name] = _load_server_config(config_path)

    try:
        model = MCPManifest.model_validate({"servers": servers})
    except ValidationError as exc:
        raise RuntimeError(f"Manifest validation failed: {exc}") from exc
    return model.model_dump(by_alias=True)


def load_and_filter_mcp(
    resolved_sources: Mapping[str, ResolvedSource],
    enabled_server_refs: list[str],
    display: Display,
) -> dict:
    selected: dict = {}
    for ref in enabled_server_refs:
        alias, server_id = split_scoped_ref(ref)
        if alias not in resolved_sources:
            raise RuntimeError(f"Unknown source alias {alias!r} in MCP reference {ref!r}")
        manifest = load_manifest(resolved_sources[alias].root, display)
        servers = manifest.get("servers") or {}
        if server_id not in servers:
            raise RuntimeError(f"MCP server {ref!r} was not found in source {alias!r}")
        if server_id in selected:
            raise RuntimeError(
                f"MCP server collision for output id {server_id!r}. "
                "Select only one source for this server id."
            )
        selected[server_id] = servers[server_id]
    return selected


def _load_server_config(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except (yaml.YAMLError, OSError) as exc:
        raise RuntimeError(f"Failed to load {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise RuntimeError(f"Invalid MCP server config {path}: expected a mapping")

    try:
        model = ServerConfig.model_validate(data)
    except ValidationError as exc:
        raise RuntimeError(f"Invalid MCP server config {path}: {exc}") from exc
    return model.model_dump(by_alias=True)
