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
    env_deps: dict[str, "EnvDependency"] = field(default_factory=dict)
    unfilled_local_vars: set[str] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)

    @property
    def has_sensitive_deps(self) -> bool:
        """True when any dependency is local or secret (not purely literal)."""
        return any(d.mode in ("local", "secret") for d in self.env_deps.values())
