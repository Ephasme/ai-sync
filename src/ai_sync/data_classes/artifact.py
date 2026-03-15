"""Artifact dataclass."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_sync.data_classes.write_spec import WriteSpec


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
    resolve_fn: Callable[[], list["WriteSpec"]]

    def resolve(self) -> list["WriteSpec"]:
        return self.resolve_fn()
