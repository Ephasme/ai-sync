"""Resolved runtime environment dataclass."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_sync.models.env_dependency import EnvDependency


@dataclass(frozen=True)
class RuntimeEnv:
    """Resolved environment for a project."""

    env: dict[str, str] = field(default_factory=dict)
    local_vars: dict[str, "EnvDependency"] = field(default_factory=dict)
    unfilled_local_vars: set[str] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)
