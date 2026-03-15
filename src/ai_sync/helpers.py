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


