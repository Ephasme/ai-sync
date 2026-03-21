"""Artifact bundle dataclass."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ai_sync.models.binary_dependency import BinaryDependency
from ai_sync.models.env_dependency import EnvDependency


@dataclass(frozen=True)
class ArtifactBundle:
    metadata: dict[str, Any]
    prompt: str | None
    env_dependencies: dict[str, EnvDependency] = field(default_factory=dict)
    binary_dependencies: list[BinaryDependency] = field(default_factory=list)
