"""API router for the ai-sync web UI."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError

from ai_sync.data_classes.resolved_source import ResolvedSource
from ai_sync.models import ProjectManifest
from ai_sync.services.buffer_display_service import BufferDisplayService
from ai_sync.web.dependencies import (
    get_config_root,
    get_container,
    get_project_root,
    get_project_root_optional,
    get_workspace_root,
)

api_router = APIRouter()

_MANIFEST_SELECTION_SECTIONS = {"agents", "skills", "commands", "rules", "mcp_servers"}
_EMPTY_SELECTIONS = {section: [] for section in _MANIFEST_SELECTION_SECTIONS}


class ManifestSelectionChange(BaseModel):
    section: str
    scoped_ref: str
    enabled: bool


class ManifestPatchRequest(BaseModel):
    changes: list[ManifestSelectionChange] = Field(default_factory=list)


@api_router.get("/status")
def get_status(
    request: Request,
    container=Depends(get_container),
    workspace_root: Path = Depends(get_workspace_root),
    project_root: Path | None = Depends(get_project_root_optional),
) -> dict[str, Any]:
    if project_root is None:
        return {
            "initialized": False,
            "workspace_root": str(workspace_root),
            "project_root": None,
            "manifest_path": None,
            "manifest": _empty_manifest(),
            "sources": [],
            "selections": _empty_selections(),
        }

    manifest_service = container.project_manifest_service()
    source_resolver = container.source_resolver_service()
    manifest_path = manifest_service.resolve_project_manifest_path(project_root)
    manifest = manifest_service.resolve_project_manifest(project_root)
    resolved_sources = source_resolver.resolve_sources(project_root, manifest)
    return {
        "initialized": True,
        "workspace_root": str(request.app.state.workspace_root),
        "project_root": str(project_root),
        "manifest_path": str(manifest_path),
        "manifest": manifest.model_dump(by_alias=True),
        "sources": [
            _serialize_resolved_source(source)
            for source in sorted(resolved_sources.values(), key=lambda item: item.alias)
        ],
        "selections": _serialize_selections(manifest),
    }


@api_router.get("/sources/{alias}/catalog")
def get_source_catalog(
    alias: str,
    container=Depends(get_container),
    project_root: Path = Depends(get_project_root),
) -> dict[str, Any]:
    manifest_service = container.project_manifest_service()
    source_resolver = container.source_resolver_service()
    catalog_service = container.source_catalog_service()
    manifest = manifest_service.resolve_project_manifest(project_root)
    resolved_sources = source_resolver.resolve_sources(project_root, manifest)
    source = resolved_sources.get(alias)
    if source is None:
        raise HTTPException(status_code=404, detail=f"Unknown source alias: {alias}")
    entries = catalog_service.catalog_source(source=source, manifest=manifest)
    return {
        "alias": alias,
        "entries": [asdict(entry) for entry in entries],
    }


@api_router.get("/manifest")
def get_manifest(
    container=Depends(get_container),
    project_root: Path = Depends(get_project_root),
) -> dict[str, Any]:
    manifest_service = container.project_manifest_service()
    manifest_path = manifest_service.resolve_project_manifest_path(project_root)
    manifest = manifest_service.resolve_project_manifest(project_root)
    raw_manifest = manifest_path.read_text(encoding="utf-8")
    return {
        "manifest_path": str(manifest_path),
        "raw": raw_manifest,
        "manifest": manifest.model_dump(by_alias=True),
    }


@api_router.get("/plan")
def get_plan(
    request: Request,
    container=Depends(get_container),
    project_root: Path = Depends(get_project_root),
    config_root: Path = Depends(get_config_root),
) -> dict[str, Any]:
    display = BufferDisplayService()
    try:
        plan_context = container.plan_service().assemble_plan_context(
            project_root,
            config_root,
            display,
        )
    except RuntimeError as exc:
        request.app.state.cached_plan_context = None
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    request.app.state.cached_plan_context = plan_context
    return _serialize_plan(plan_context=plan_context, display=display)


@api_router.patch("/manifest")
def patch_manifest(
    payload: ManifestPatchRequest,
    request: Request,
    container=Depends(get_container),
    project_root: Path = Depends(get_project_root),
) -> dict[str, Any]:
    manifest_service = container.project_manifest_service()
    manifest_path = manifest_service.resolve_project_manifest_path(project_root)
    data = manifest_service.load_yaml_file(manifest_path)

    for change in payload.changes:
        if change.section not in _MANIFEST_SELECTION_SECTIONS:
            raise HTTPException(status_code=400, detail=f"Unsupported manifest section: {change.section}")
        current = data.setdefault(change.section, [])
        if not isinstance(current, list):
            raise HTTPException(
                status_code=400,
                detail=f"Manifest section {change.section!r} must be a list.",
            )
        if change.enabled:
            if change.scoped_ref not in current:
                current.append(change.scoped_ref)
        else:
            data[change.section] = [item for item in current if item != change.scoped_ref]
            if not data[change.section]:
                data.pop(change.section, None)

    try:
        manifest = ProjectManifest.model_validate(data)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    manifest_path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    request.app.state.cached_plan_context = None
    return {
        "manifest_path": str(manifest_path),
        "raw": manifest_path.read_text(encoding="utf-8"),
        "manifest": manifest.model_dump(by_alias=True),
    }


@api_router.post("/apply")
def apply_plan(
    request: Request,
    container=Depends(get_container),
    project_root: Path = Depends(get_project_root),
) -> dict[str, Any]:
    cached_plan_context = request.app.state.cached_plan_context
    if cached_plan_context is None:
        raise HTTPException(status_code=400, detail="No cached plan context. Run GET /api/plan first.")

    manifest_service = container.project_manifest_service()
    manifest_path = manifest_service.resolve_project_manifest_path(project_root)
    current_fingerprint = manifest_service.manifest_fingerprint(manifest_path)
    if current_fingerprint != cached_plan_context.plan.manifest_fingerprint:
        request.app.state.cached_plan_context = None
        raise HTTPException(status_code=409, detail="Cached plan is stale. Run GET /api/plan again.")

    display = BufferDisplayService()
    exit_code = container.apply_service().run_apply(
        project_root=project_root,
        resolved_artifacts=cached_plan_context.resolved_artifacts,
        display=display,
    )
    request.app.state.cached_plan_context = None
    return {
        "exit_code": exit_code,
        "messages": display.messages,
        "warnings": _warning_messages(display.messages),
    }


def _serialize_resolved_source(source: ResolvedSource) -> dict[str, Any]:
    return {
        "alias": source.alias,
        "source": source.source,
        "version": source.version,
        "root": str(source.root),
        "kind": source.kind,
        "fingerprint": source.fingerprint,
        "portability_warning": source.portability_warning,
    }


def _serialize_selections(manifest: ProjectManifest) -> dict[str, list[str]]:
    return {
        "agents": list(manifest.agents),
        "skills": list(manifest.skills),
        "commands": list(manifest.commands),
        "rules": list(manifest.rules),
        "mcp_servers": list(manifest.mcp_servers),
    }


def _empty_manifest() -> dict[str, Any]:
    return {
        "sources": {},
        "agents": [],
        "skills": [],
        "commands": [],
        "rules": [],
        "mcp_servers": [],
        "settings": {},
    }


def _empty_selections() -> dict[str, list[str]]:
    return {section: list(items) for section, items in _EMPTY_SELECTIONS.items()}


def _serialize_plan(
    *,
    plan_context,
    display: BufferDisplayService,
) -> dict[str, Any]:
    plan = plan_context.plan.model_dump()
    for action in plan.get("actions", []):
        target = action.get("target")
        if isinstance(target, str):
            action["display_target"] = _relative_target(target, plan_context.plan.project_root)
    return {
        "plan": plan,
        "messages": display.messages,
        "warnings": _warning_messages(display.messages),
    }


def _warning_messages(messages: list[dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    for message in messages:
        style = message.get("style")
        if style != "warning":
            continue
        if message.get("kind") == "print":
            warnings.append(str(message.get("message", "")))
            continue
        if message.get("kind") == "panel":
            title = str(message.get("title", "")).strip()
            content = str(message.get("content", "")).strip()
            warnings.append(": ".join(part for part in (title, content) if part))
    return warnings


def _relative_target(target: str, project_root: str) -> str:
    root = project_root.rstrip("/\\")
    if target.startswith(root + "/") or target.startswith(root + "\\"):
        return target[len(root) + 1 :]
    return target
