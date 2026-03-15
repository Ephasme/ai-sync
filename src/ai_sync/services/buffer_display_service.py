"""Buffered display service implementation for API responses."""

from __future__ import annotations

from typing import Any

from ai_sync.services.display_service import DisplayService, PanelStyle, PrintStyle, RuleStyle


class BufferDisplayService(DisplayService):
    """Collect display events for later serialization in API responses."""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    def rule(self, title: str, style: RuleStyle = "section") -> None:
        self.messages.append({"kind": "rule", "style": style, "title": title})

    def print(self, msg: str, style: PrintStyle = "normal") -> None:
        self.messages.append({"kind": "print", "style": style, "message": msg})

    def panel(self, content: str, *, title: str = "", style: PanelStyle = "normal") -> None:
        self.messages.append(
            {
                "kind": "panel",
                "style": style,
                "title": title,
                "content": content,
            }
        )

    def table(self, headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> None:
        self.messages.append(
            {
                "kind": "table",
                "headers": list(headers),
                "rows": [list(row) for row in rows],
            }
        )
