"""Plain text display implementation."""

from __future__ import annotations

from .base import Display, PanelStyle, PrintStyle, RuleStyle


class PlainDisplay(Display):
    def rule(self, title: str, style: RuleStyle = "section") -> None:
        print(f"--- {title} ---")

    def print(self, msg: str, style: PrintStyle = "normal") -> None:
        if style == "warning":
            print(f"Warning: {msg}")
        else:
            print(msg)

    def panel(self, content: str, *, title: str = "", style: PanelStyle = "normal") -> None:
        if title:
            prefix = "ERROR: " if style == "error" else ""
            print(f"=== {prefix}{title} ===")
        if content:
            print(content)
        if title or content:
            print()

    def table(self, headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> None:
        if not headers and not rows:
            return
        col_widths = [
            max(len(str(h)), max((len(str(r[i])) for r in rows), default=0))
            for i, h in enumerate(headers)
        ]
        fmt = "  ".join(f"{{:<{w}}}" for w in col_widths)
        print(fmt.format(*headers))
        print("-" * (sum(col_widths) + 2 * (len(headers) - 1)))
        for row in rows:
            print(fmt.format(*row))
