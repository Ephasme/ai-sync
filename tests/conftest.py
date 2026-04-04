"""Shared test fixtures."""

from __future__ import annotations

import pytest

from ai_sync.services.tool_version_service import ToolVersionService

_STUB_VERSIONS = {"codex": "0.0.0", "cursor": "0.0.0", "gemini": "0.0.0"}
REAL_DETECT_CLIENT_VERSIONS = ToolVersionService.detect_client_versions


@pytest.fixture(autouse=True)
def _no_subprocess_version_detection(monkeypatch):
    """Prevent real subprocess calls to detect client versions during tests."""
    monkeypatch.setattr(
        ToolVersionService,
        "detect_client_versions",
        lambda self: _STUB_VERSIONS,
    )
