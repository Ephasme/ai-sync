"""Project manifest model and scoped reference helpers."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_sync.models.source_config import SourceConfig

ALIAS_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
SUPPORTED_MANIFEST_SCHEMAS: set[int] = {1}
DEFAULT_PROJECT_MANIFEST_FILENAME = ".ai-sync.yaml"
LOCAL_PROJECT_MANIFEST_FILENAME = ".ai-sync.local.yaml"
PROJECT_MANIFEST_FILENAMES = (
    LOCAL_PROJECT_MANIFEST_FILENAME,
    DEFAULT_PROJECT_MANIFEST_FILENAME,
)


class ProjectManifest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_version: int = 1
    sources: dict[str, SourceConfig] = Field(default_factory=dict)
    agents: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    commands: list[str] = Field(default_factory=list)
    rules: list[str] = Field(default_factory=list)
    mcp_servers: list[str] = Field(default_factory=list)
    settings: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_scoped_references(self) -> "ProjectManifest":
        invalid_aliases = sorted(
            alias for alias in self.sources if not ALIAS_RE.fullmatch(alias)
        )
        if invalid_aliases:
            bad = ", ".join(invalid_aliases)
            raise ValueError(
                f"Invalid source alias(es): {bad}. Aliases must match [a-z0-9]([a-z0-9-]*[a-z0-9])?."
            )

        for ref in self.iter_all_resource_refs():
            alias, _ = split_scoped_ref(ref)
            if alias not in self.sources:
                raise ValueError(
                    f"Unknown source alias {alias!r} in scoped reference {ref!r}."
                )
        return self

    def iter_all_resource_refs(self) -> list[str]:
        return [
            *self.agents,
            *self.skills,
            *self.commands,
            *self.rules,
            *self.mcp_servers,
        ]


def split_scoped_ref(ref: str) -> tuple[str, str]:
    if "/" not in ref:
        raise ValueError(
            f"Scoped reference must be in the form <sourceAlias>/<resourceId>, got: {ref!r}"
        )
    alias, resource_id = ref.split("/", 1)
    if not alias or not resource_id:
        raise ValueError(
            f"Scoped reference must be in the form <sourceAlias>/<resourceId>, got: {ref!r}"
        )
    return alias, resource_id
