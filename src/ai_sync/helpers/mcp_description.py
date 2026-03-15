"""Build MCP descriptions from metadata with stable fallbacks."""

from __future__ import annotations

from ai_sync.helpers.string_metadata_value import string_metadata_value


def mcp_description(metadata: dict[str, object], fallback: str = "") -> str:
    description = string_metadata_value(metadata.get("description"), "")
    if description:
        return description
    method = string_metadata_value(metadata.get("method"), "")
    if method:
        return f"{method} MCP server"
    return fallback
