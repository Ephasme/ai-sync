"""Rich display implementation."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .base import Display, PanelStyle, PrintStyle, RuleStyle


class RichDisplay(Display):
    _RULE_STYLES: dict[RuleStyle, str] = {
        "section": "bold cyan",
        "error": "bold red",
        "success": "bold green",
        "info": "bold blue",
    }
    _PRINT_STYLES: dict[PrintStyle, str] = {
        "normal": "",
        "dim": "dim",
        "warning": "yellow",
        "success": "bold green",
        "info": "cyan",
    }
    _PANEL_STYLES: dict[PanelStyle, str] = {
        "normal": "",
        "error": "red",
        "success": "green",
        "info": "blue",
    }

    def __init__(self) -> None:
        self._console = Console()

    def rule(self, title: str, style: RuleStyle = "section") -> None:
        s = self._RULE_STYLES[style]
        self._console.rule(f"[{s}]{title}[/{s}]")

    def print(self, msg: str, style: PrintStyle = "normal") -> None:
        s = self._PRINT_STYLES[style]
        self._console.print(f"[{s}]{msg}[/{s}]" if s else msg)

    def panel(self, content: str, *, title: str = "", style: PanelStyle = "normal") -> None:
        border = self._PANEL_STYLES[style] or "none"
        title_str = f"[bold]{title}[/bold]" if title else None
        self._console.print(Panel(content, title=title_str, border_style=border))

    def table(self, headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> None:
        t = Table(show_header=True, header_style="bold", box=None)
        for h in headers:
            t.add_column(h)
        for row in rows:
            t.add_row(*row)
        self._console.print(t)
