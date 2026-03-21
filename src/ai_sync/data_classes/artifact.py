"""Artifact dataclass."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_sync.data_classes.apply_spec import ApplySpec
    from ai_sync.models.env_dependency import EnvDependency


@dataclass(frozen=True)
class Artifact:
    kind: str
    resource: str
    name: str
    description: str
    source_alias: str
    plan_key: str
    secret_backed: bool
    client: str
    resolve_fn: Callable[[], Sequence["ApplySpec"]]
    env_dependencies: dict[str, "EnvDependency"] = field(default_factory=dict)

    def resolve(self) -> Sequence["ApplySpec"]:
        return self.resolve_fn()
