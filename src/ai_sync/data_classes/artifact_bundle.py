"""Artifact bundle dataclass."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ArtifactBundle:
    metadata: dict[str, Any]
    prompt: str | None
