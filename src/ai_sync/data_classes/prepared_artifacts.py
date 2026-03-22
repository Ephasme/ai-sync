"""Shared prepared-artifacts boundary for the universal pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_sync.data_classes.prepared_mcp_server import PreparedMcpServer
    from ai_sync.models.binary_dependency import BinaryDependency


@dataclass(frozen=True)
class PreparedArtifacts:
    """Aggregate context produced by the preparation phase.

    All artifact kinds enter the same pipeline through this boundary.
    Kind-specific payloads live in dedicated fields; downstream consumers
    (collectors, binary dependency checks, plan builders) receive this single
    context instead of per-kind side channels.
    """

    mcp_servers: list["PreparedMcpServer"] = field(default_factory=list)
    has_env_file: bool = False
    binary_dependencies: list["BinaryDependency"] = field(default_factory=list)
