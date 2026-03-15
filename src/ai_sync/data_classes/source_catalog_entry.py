"""Source catalog entry dataclass."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceCatalogEntry:
    kind: str
    resource_id: str
    scoped_ref: str
    name: str
    description: str
    selected: bool
