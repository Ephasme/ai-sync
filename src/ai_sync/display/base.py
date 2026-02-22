"""Display interfaces and style types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal

RuleStyle = Literal["section", "error", "success", "info"]
PrintStyle = Literal["normal", "dim", "warning", "success", "info"]
PanelStyle = Literal["normal", "error", "success", "info"]


class Display(ABC):
    @abstractmethod
    def rule(self, title: str, style: RuleStyle = "section") -> None:
        ...

    @abstractmethod
    def print(self, msg: str, style: PrintStyle = "normal") -> None:
        ...

    @abstractmethod
    def panel(self, content: str, *, title: str = "", style: PanelStyle = "normal") -> None:
        ...

    @abstractmethod
    def table(self, headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> None:
        ...
