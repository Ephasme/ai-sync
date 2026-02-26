"""Manifest loading and validation."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from .display import Display
from .helpers import validate_servers_yaml
from .models import MCPManifest


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
    repo_roots: list[Path],
    enabled_server_ids: list[str],
    display: Display,
) -> dict:
    merged_servers: dict = {}
    for repo_root in repo_roots:
        manifest = load_manifest(repo_root, display)
        servers = manifest.get("servers") or {}
        merged_servers.update(servers)
    filtered = {sid: srv for sid, srv in merged_servers.items() if sid in enabled_server_ids}
    return filtered
