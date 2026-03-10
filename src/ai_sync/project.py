"""Project manifest loading and scoped resource helpers."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

ALIAS_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")


class SourceConfig(BaseModel):
    source: str
    version: str | None = None


class ProjectManifest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    sources: dict[str, SourceConfig] = Field(default_factory=dict)
    agents: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    commands: list[str] = Field(default_factory=list)
    rules: list[str] = Field(default_factory=list)
    mcp_servers: list[str] = Field(
        default_factory=list,
        validation_alias="mcp-servers",
        serialization_alias="mcp-servers",
    )
    settings: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_scoped_references(self) -> "ProjectManifest":
        invalid_aliases = sorted(alias for alias in self.sources if not ALIAS_RE.fullmatch(alias))
        if invalid_aliases:
            bad = ", ".join(invalid_aliases)
            raise ValueError(
                f"Invalid source alias(es): {bad}. Aliases must match [a-z0-9]([a-z0-9-]*[a-z0-9])?."
            )

        for ref in self.iter_all_resource_refs():
            alias, _ = split_scoped_ref(ref)
            if alias not in self.sources:
                raise ValueError(f"Unknown source alias {alias!r} in scoped reference {ref!r}.")
        return self

    def iter_all_resource_refs(self) -> list[str]:
        return [*self.agents, *self.skills, *self.commands, *self.rules, *self.mcp_servers]


def split_scoped_ref(ref: str) -> tuple[str, str]:
    if "/" not in ref:
        raise ValueError(f"Scoped reference must be in the form <sourceAlias>/<resourceId>, got: {ref!r}")
    alias, resource_id = ref.split("/", 1)
    if not alias or not resource_id:
        raise ValueError(f"Scoped reference must be in the form <sourceAlias>/<resourceId>, got: {ref!r}")
    return alias, resource_id


def _load_yaml_file(path: Path) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (yaml.YAMLError, OSError) as exc:
        raise RuntimeError(f"Failed to load {path}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise RuntimeError(f"Expected a mapping in {path}, got {type(data).__name__}")
    return data


def manifest_fingerprint(path: Path) -> str:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise RuntimeError(f"Failed to read {path}: {exc}") from exc
    return hashlib.sha256(content).hexdigest()


def resolve_project_manifest(project_root: Path) -> ProjectManifest:
    ai_sync_yaml = project_root / ".ai-sync.yaml"
    if not ai_sync_yaml.exists():
        raise RuntimeError(f"No .ai-sync.yaml found in {project_root}. Create one first.")
    data = _load_yaml_file(ai_sync_yaml)
    try:
        return ProjectManifest.model_validate(data)
    except ValidationError as exc:
        raise RuntimeError(f"Invalid .ai-sync.yaml: {exc}") from exc


def find_project_root(start: Path | None = None) -> Path | None:
    current = (start or Path.cwd()).resolve()
    while True:
        if (current / ".ai-sync.yaml").exists():
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent
