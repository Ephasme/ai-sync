"""Plan context dataclass."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_sync.data_classes.prepared_artifacts import PreparedArtifacts
    from ai_sync.data_classes.resolved_artifact_set import ResolvedArtifactSet
    from ai_sync.data_classes.resolved_source import ResolvedSource
    from ai_sync.data_classes.runtime_env import RuntimeEnv
    from ai_sync.models.apply_plan import ApplyPlan
    from ai_sync.models.project_manifest import ProjectManifest


@dataclass(frozen=True)
class PlanContext:
    plan: "ApplyPlan"
    manifest: "ProjectManifest"
    resolved_sources: dict[str, "ResolvedSource"]
    prepared_artifacts: "PreparedArtifacts"
    runtime_env: "RuntimeEnv"
    secrets: dict
    resolved_artifacts: "ResolvedArtifactSet"
