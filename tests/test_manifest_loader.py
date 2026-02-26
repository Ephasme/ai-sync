from __future__ import annotations

from pathlib import Path

import pytest

from ai_sync.manifest_loader import load_and_filter_mcp, load_manifest


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


def test_load_and_filter_mcp_single_repo(tmp_path: Path) -> None:
    display = FakeDisplay()
    repo = tmp_path / "repo-a"
    repo.mkdir()
    (repo / "mcp-servers.yaml").write_text(
        "servers:\n  srv-a:\n    method: stdio\n    command: npx\n  srv-b:\n    method: stdio\n    command: npx\n",
        encoding="utf-8",
    )
    result = load_and_filter_mcp([repo], ["srv-a"], display)
    assert "srv-a" in result
    assert "srv-b" not in result


def test_load_and_filter_mcp_last_repo_wins(tmp_path: Path) -> None:
    display = FakeDisplay()
    repo_a = tmp_path / "repo-a"
    repo_a.mkdir()
    (repo_a / "mcp-servers.yaml").write_text(
        "servers:\n  fetch:\n    method: stdio\n    command: old-cmd\n",
        encoding="utf-8",
    )
    repo_b = tmp_path / "repo-b"
    repo_b.mkdir()
    (repo_b / "mcp-servers.yaml").write_text(
        "servers:\n  fetch:\n    method: stdio\n    command: new-cmd\n",
        encoding="utf-8",
    )
    result = load_and_filter_mcp([repo_a, repo_b], ["fetch"], display)
    assert result["fetch"]["command"] == "new-cmd"


def test_load_and_filter_mcp_merges_servers(tmp_path: Path) -> None:
    display = FakeDisplay()
    repo_a = tmp_path / "repo-a"
    repo_a.mkdir()
    (repo_a / "mcp-servers.yaml").write_text(
        "servers:\n  srv-a:\n    method: stdio\n    command: a\n",
        encoding="utf-8",
    )
    repo_b = tmp_path / "repo-b"
    repo_b.mkdir()
    (repo_b / "mcp-servers.yaml").write_text(
        "servers:\n  srv-b:\n    method: stdio\n    command: b\n",
        encoding="utf-8",
    )
    result = load_and_filter_mcp([repo_a, repo_b], ["srv-a", "srv-b"], display)
    assert "srv-a" in result
    assert "srv-b" in result
