"""Development helpers for the ai-sync web UI."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from ai_sync.di import bootstrap_runtime
from ai_sync.web.app import create_app


def create_dev_app() -> FastAPI:
    """Create a reload-friendly FastAPI app for local UI development."""

    runtime = bootstrap_runtime()
    config_root = runtime.container.config_store_service().get_config_root()
    config_path = config_root / "config.toml"
    if not config_path.exists():
        raise RuntimeError("Run `ai-sync install` first.")

    project_root = runtime.container.project_locator_service().find_project_root()

    return create_app(
        container=runtime.container,
        project_root=project_root,
        config_root=config_root,
        workspace_root=Path.cwd().resolve(),
    )
