"""FastAPI application factory for the ai-sync web UI."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ai_sync.web.api import api_router

if TYPE_CHECKING:
    from ai_sync.di import AppContainer


class SPAStaticFiles(StaticFiles):
    """Serve built frontend assets and fall back to index.html for SPA routes."""

    async def get_response(self, path: str, scope):  # type: ignore[override]
        try:
            return await super().get_response(path, scope)
        except Exception:
            return await super().get_response("index.html", scope)


def create_app(
    *,
    container: "AppContainer",
    project_root: Path | None,
    config_root: Path,
    workspace_root: Path | None = None,
) -> FastAPI:
    """Create the FastAPI application used by `ai-sync ui`."""

    app = FastAPI(title="ai-sync web UI")
    app.state.container = container
    app.state.project_root = project_root
    app.state.workspace_root = (workspace_root or project_root or Path.cwd()).resolve()
    app.state.config_root = config_root
    app.state.cached_plan_context = None

    app.include_router(api_router, prefix="/api")

    static_dir = Path(__file__).resolve().parent / "static"
    app.mount(
        "/",
        SPAStaticFiles(directory=static_dir, html=True, check_dir=False),
        name="spa",
    )

    return app
