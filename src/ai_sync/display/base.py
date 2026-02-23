"""Display interfaces and style types."""

from __future__ import annotations

from typing import Literal, Protocol

RuleStyle = Literal["section", "error", "success", "info"]
PrintStyle = Literal["normal", "dim", "warning", "success", "info"]
PanelStyle = Literal["normal", "error", "success", "info"]


class Display(Protocol):
    def rule(self, title: str, style: RuleStyle = "section") -> None:
        ...

    def print(self, msg: str, style: PrintStyle = "normal") -> None:
        ...

    def panel(self, content: str, *, title: str = "", style: PanelStyle = "normal") -> None:
        ...

    def table(self, headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> None:
        ...
