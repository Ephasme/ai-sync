"""Shared helper utilities for ai_sync."""

from __future__ import annotations

import re
from pathlib import Path


def to_kebab_case(name: str) -> str:
    return re.sub(r"[_ ]+", "-", name).lower()


def validate_client_settings(settings: object) -> list[str]:
    if settings is None:
        return []
    if not isinstance(settings, dict):
        return ["Client settings must be a mapping."]
    errors: list[str] = []
    allowed_top = {"experimental", "subagents", "mode", "tools"}
    unknown_top = sorted(set(settings) - allowed_top)
    if unknown_top:
        errors.append(f"Unknown client setting(s): {', '.join(unknown_top)}")
    if "experimental" in settings and not isinstance(settings["experimental"], bool):
        errors.append("experimental must be true/false")
    if "subagents" in settings and not isinstance(settings["subagents"], bool):
        errors.append("subagents must be true/false")
    if "mode" in settings:
        val = settings.get("mode")
        if val not in (None, "", "strict", "normal", "yolo"):
            errors.append(f"Invalid mode: {val!r}")
    tools = settings.get("tools")
    if tools is not None:
        if not isinstance(tools, dict):
            errors.append("tools must be a mapping")
        else:
            unknown_tools = sorted(set(tools) - {"sandbox"})
            if unknown_tools:
                errors.append(f"Unknown tools setting(s): {', '.join(unknown_tools)}")
            if "sandbox" in tools and not isinstance(tools["sandbox"], bool):
                errors.append("tools.sandbox must be true/false")
    return errors


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def extract_description(content: str) -> str:
    match = re.search(r"## Task\s+(.*)", content, re.IGNORECASE | re.DOTALL)
    if match:
        desc = match.group(1).strip().split("\n")[0]
        return desc[:150] + "..." if len(desc) > 150 else desc
    for line in content.splitlines():
        if line.strip() and not line.startswith("#"):
            return line.strip()[:100]
    return "AI Agent"


def validate_servers_yaml(data: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["mcp-servers.yaml root must be a mapping"]
    servers = data.get("servers")
    if servers is not None and not isinstance(servers, dict):
        errors.append("'servers' must be a mapping")
        return errors
    for sid, srv in (servers or {}).items():
        if not isinstance(srv, dict):
            errors.append(f"Server '{sid}' must be a mapping")
            continue
        if "method" in srv and srv["method"] not in ("stdio", "http", "sse"):
            errors.append(
                f"Server '{sid}': invalid method '{srv['method']}' (expected stdio/http/sse)"
            )
        if "timeout" in srv:
            errors.append(
                f"Server '{sid}': 'timeout' is no longer supported; use 'timeout_seconds'"
            )
        if srv.get("method", "stdio") == "stdio" and not srv.get("command"):
            errors.append(f"Server '{sid}': stdio server must have a 'command'")
        if "timeout_seconds" in srv:
            timeout_seconds = srv.get("timeout_seconds")
            if not isinstance(timeout_seconds, (int, float)):
                errors.append(
                    f"Server '{sid}': 'timeout_seconds' must be a number, got {type(timeout_seconds).__name__}"
                )
            elif timeout_seconds < 0:
                errors.append(f"Server '{sid}': 'timeout_seconds' must be >= 0")
    return errors
