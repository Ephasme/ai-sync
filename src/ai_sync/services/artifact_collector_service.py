"""Protocol for artifact collector services."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ai_sync.clients.base import Client
    from ai_sync.data_classes.artifact import Artifact
    from ai_sync.data_classes.resolved_source import ResolvedSource
    from ai_sync.data_classes.runtime_env import RuntimeEnv
    from ai_sync.models import ProjectManifest


class ArtifactCollectorService(Protocol):
    """Typed contract shared by artifact collector services."""

    def collect_artifacts(
        self,
        *,
        project_root: Path,
        manifest: "ProjectManifest",
        resolved_sources: dict[str, "ResolvedSource"],
        runtime_env: "RuntimeEnv",
        mcp_manifest: dict,
        clients: list["Client"],
    ) -> list["Artifact"]: ...
