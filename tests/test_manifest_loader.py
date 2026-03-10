from __future__ import annotations

from pathlib import Path

import pytest

from ai_sync.manifest_loader import load_and_filter_mcp, load_manifest
from ai_sync.source_resolver import ResolvedSource


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


def _source(alias: str, root: Path) -> ResolvedSource:
    return ResolvedSource(alias=alias, source=str(root), version=None, root=root, kind="local", fingerprint="abc")


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


def test_load_and_filter_mcp_by_scoped_refs(tmp_path: Path) -> None:
    display = FakeDisplay()
    company = tmp_path / "company"
    company.mkdir()
    (company / "mcp-servers.yaml").write_text(
        "servers:\n  srv-a:\n    method: stdio\n    command: npx\n  srv-b:\n    method: stdio\n    command: npx\n",
        encoding="utf-8",
    )
    result = load_and_filter_mcp({"company": _source("company", company)}, ["company/srv-a"], display)
    assert "srv-a" in result
    assert "srv-b" not in result


def test_load_and_filter_mcp_rejects_missing_server(tmp_path: Path) -> None:
    display = FakeDisplay()
    company = tmp_path / "company"
    company.mkdir()
    (company / "mcp-servers.yaml").write_text(
        "servers:\n  srv-a:\n    method: stdio\n    command: npx\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="was not found"):
        load_and_filter_mcp({"company": _source("company", company)}, ["company/srv-b"], display)


def test_load_and_filter_mcp_rejects_colliding_output_ids(tmp_path: Path) -> None:
    display = FakeDisplay()
    company = tmp_path / "company"
    company.mkdir()
    (company / "mcp-servers.yaml").write_text(
        "servers:\n  fetch:\n    method: stdio\n    command: company\n",
        encoding="utf-8",
    )
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "mcp-servers.yaml").write_text(
        "servers:\n  fetch:\n    method: stdio\n    command: frontend\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="collision"):
        load_and_filter_mcp(
            {
                "company": _source("company", company),
                "frontend": _source("frontend", frontend),
            },
            ["company/fetch", "frontend/fetch"],
            display,
        )
