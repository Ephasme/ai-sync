"""Client adapters for Codex, Cursor, Gemini."""
from .base import Client
from .codex import CodexClient
from .cursor import CursorClient
from .gemini import GeminiClient

CLIENTS: list[Client] = [CodexClient(), CursorClient(), GeminiClient()]

__all__ = ["Client", "CodexClient", "CursorClient", "GeminiClient", "CLIENTS"]
