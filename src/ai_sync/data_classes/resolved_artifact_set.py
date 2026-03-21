"""Resolved artifact set dataclass."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_sync.data_classes.apply_spec import ApplySpec
    from ai_sync.data_classes.artifact import Artifact


@dataclass(frozen=True)
class ResolvedArtifactSet:
    """Artifacts paired with resolved ApplySpecs, computed once."""

    entries: list[tuple["Artifact", Sequence["ApplySpec"]]]
    desired_targets: set[tuple[str, str, str]]
