"""Manifest loading and validation."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from .display import Display
from .helpers import validate_servers_yaml
from .models import MCPManifest


def load_manifest(mcp_root: Path, display: Display) -> dict:
    servers_path = mcp_root / "servers.yaml"
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
        display.print(f"servers.yaml: {err}", style="warning")
    try:
        model = MCPManifest.model_validate(data)
    except ValidationError as exc:
        raise RuntimeError(f"Manifest validation failed: {exc}") from exc
    return model.model_dump(by_alias=True)
