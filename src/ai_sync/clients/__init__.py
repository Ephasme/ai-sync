"""Client adapters for Codex, Cursor, Gemini."""

from pathlib import Path

from .base import Client
from .codex import CodexClient
from .cursor import CursorClient
from .gemini import GeminiClient


def create_clients(project_root: Path) -> list[Client]:
    return [CodexClient(project_root), CursorClient(project_root), GeminiClient(project_root)]


__all__ = ["Client", "CodexClient", "CursorClient", "GeminiClient", "create_clients"]
