"""FastAPI dependencies for the ai-sync web application."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

from fastapi import HTTPException, Request

from ai_sync.data_classes.plan_context import PlanContext

if TYPE_CHECKING:
    from ai_sync.di import AppContainer


def get_container(request: Request) -> "AppContainer":
    return cast("AppContainer", request.app.state.container)


def get_project_root_optional(request: Request) -> Path | None:
    return cast(Path | None, request.app.state.project_root)


def get_project_root(request: Request) -> Path:
    project_root = get_project_root_optional(request)
    if project_root is None:
        raise HTTPException(
            status_code=409,
            detail="No .ai-sync.local.yaml or .ai-sync.yaml found in the current workspace. Create one first.",
        )
    return project_root


def get_workspace_root(request: Request) -> Path:
    return cast(Path, request.app.state.workspace_root)


def get_config_root(request: Request) -> Path:
    return cast(Path, request.app.state.config_root)


def get_cached_plan_context(request: Request) -> PlanContext | None:
    return cast(PlanContext | None, request.app.state.cached_plan_context)
