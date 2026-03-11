"""Requirements manifest loading and filtering."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

import yaml
from pydantic import ValidationError

from .display import Display
from .models import Requirement, RequirementsManifest
from .project import split_scoped_ref
from .source_resolver import ResolvedSource


def _load_requirements(repo_root: Path, display: Display) -> list[Requirement]:
    requirements_path = repo_root / "requirements.yaml"
    if not requirements_path.exists():
        return []
    try:
        with open(requirements_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except (yaml.YAMLError, OSError) as exc:
        display.print(f"Failed to load {requirements_path}: {exc}", style="warning")
        return []
    try:
        model = RequirementsManifest.model_validate(data)
    except ValidationError as exc:
        raise RuntimeError(f"requirements.yaml validation failed: {exc}") from exc
    return model.requirements


def load_and_filter_requirements(
    resolved_sources: Mapping[str, ResolvedSource],
    enabled_server_refs: list[str],
    display: Display,
) -> list[Requirement]:
    selected_by_alias: dict[str, set[str]] = {}
    for ref in enabled_server_refs:
        alias, server_id = split_scoped_ref(ref)
        selected_by_alias.setdefault(alias, set()).add(server_id)

    merged: dict[str, Requirement] = {}
    for alias, server_ids in selected_by_alias.items():
        if alias not in resolved_sources:
            raise RuntimeError(f"Unknown source alias {alias!r} in requirements selection.")
        for req in _load_requirements(resolved_sources[alias].root, display):
            if not (set(req.servers) & server_ids):
                continue
            existing = merged.get(req.name)
            if existing is None:
                merged[req.name] = req
                continue
            if existing.version.model_dump() != req.version.model_dump():
                raise RuntimeError(
                    f"Requirement collision for {req.name!r} across selected sources. "
                    "ai-sync does not merge conflicting requirement definitions."
                )
            existing.servers = sorted(set(existing.servers) | set(req.servers))
    return list(merged.values())
