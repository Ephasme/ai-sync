"""Manifest loading and validation."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

import yaml
from pydantic import ValidationError

from .display import Display
from .helpers import validate_servers_yaml
from .models import MCPManifest
from .project import split_scoped_ref
from .source_resolver import ResolvedSource


def load_manifest(mcp_root: Path, display: Display) -> dict:
    servers_path = mcp_root / "mcp-servers.yaml"
    if not servers_path.exists():
        return {}
    try:
        with open(servers_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except (yaml.YAMLError, OSError) as exc:
        display.print(f"Failed to load {servers_path}: {exc}", style="warning")
        return {}
    errors = validate_servers_yaml(data)
    for err in errors:
        display.print(f"mcp-servers.yaml: {err}", style="warning")
    try:
        model = MCPManifest.model_validate(data)
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
                "Select only one source for this server id in V1."
            )
        selected[server_id] = servers[server_id]
    return selected
