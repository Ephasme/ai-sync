from __future__ import annotations

from pathlib import Path

import pytest

from ai_sync.manifest_loader import load_manifest


class FakeDisplay:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def rule(self, title: str, style: str = "section") -> None:
        self.messages.append((style, title))

    def print(self, msg: str, style: str = "normal") -> None:
        self.messages.append((style, msg))

    def panel(self, content: str, *, title: str = "", style: str = "normal") -> None:
        self.messages.append((style, f"{title}:{content}"))

    def table(self, headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> None:
        self.messages.append(("table", ",".join(headers)))


def test_load_manifest_missing_returns_empty(tmp_path: Path) -> None:
    display = FakeDisplay()
    assert load_manifest(tmp_path, display) == {}


def test_load_manifest_invalid_yaml_warns(tmp_path: Path) -> None:
    display = FakeDisplay()
    (tmp_path / "mcp-servers.yaml").write_text("servers: [", encoding="utf-8")
    data = load_manifest(tmp_path, display)
    assert data == {}
    assert any("Failed to load" in msg for _, msg in display.messages)


def test_load_manifest_validation_error_raises(tmp_path: Path) -> None:
    display = FakeDisplay()
    (tmp_path / "mcp-servers.yaml").write_text("servers: 123\n", encoding="utf-8")
    with pytest.raises(RuntimeError):
        load_manifest(tmp_path, display)


def test_load_manifest_valid(tmp_path: Path) -> None:
    display = FakeDisplay()
    (tmp_path / "mcp-servers.yaml").write_text(
        "servers:\n  ok:\n    method: stdio\n    command: npx\n",
        encoding="utf-8",
    )
    data = load_manifest(tmp_path, display)
    assert "servers" in data
    assert "ok" in data["servers"]
