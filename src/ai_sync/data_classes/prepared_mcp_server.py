"""Prepared MCP server entry preserving provenance and runtime state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_sync.models.env_dependency import EnvDependency


@dataclass(frozen=True)
class PreparedMcpServer:
    """A fully validated and runtime-resolved MCP server entry.

    Carries provenance (scoped_ref, source_alias, server_id), the original
    validated source configuration, the runtime-rendered configuration after
    env interpolation and client-override resolution, and the typed env
    dependencies needed downstream by artifact collection and requirement
    checks.
    """

    scoped_ref: str
    source_alias: str
    server_id: str
    source_config: dict
    runtime_config: dict
    env_dependencies: dict[str, "EnvDependency"] = field(default_factory=dict)
