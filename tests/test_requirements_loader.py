from __future__ import annotations

from pathlib import Path

import pytest

from ai_sync.display import PlainDisplay
from ai_sync.requirements_loader import load_and_filter_requirements
from ai_sync.source_resolver import ResolvedSource


def _source(alias: str, root: Path) -> ResolvedSource:
    return ResolvedSource(alias=alias, source=str(root), version=None, root=root, kind="local", fingerprint="abc")


def _write_requirements(repo_root: Path, content: str) -> None:
    (repo_root / "requirements.yaml").write_text(content, encoding="utf-8")


def test_merge_requirements_same_name_and_version_unions_servers(tmp_path: Path) -> None:
    display = PlainDisplay()

    primary = tmp_path / "primary"
    primary.mkdir()
    _write_requirements(
        primary,
        (
            "requirements:\n"
            "  - name: npx\n"
            "    servers: [context7, filesystem, playwright]\n"
            "    version:\n"
            "      require: ~10.0.0\n"
        ),
    )

    secondary = tmp_path / "secondary"
    secondary.mkdir()
    _write_requirements(
        secondary,
        (
            "requirements:\n"
            "  - name: npx\n"
            "    servers: [context7, filesystem, playwright, slack, notion]\n"
            "    version:\n"
            "      require: ~10.0.0\n"
        ),
    )

    selected = load_and_filter_requirements(
        {"primary": _source("primary", primary), "secondary": _source("secondary", secondary)},
        ["primary/context7", "secondary/slack"],
        display,
    )

    assert len(selected) == 1
    assert selected[0].name == "npx"
    assert selected[0].version.require == "~10.0.0"
    assert selected[0].servers == ["context7", "filesystem", "notion", "playwright", "slack"]


def test_merge_requirements_same_name_with_different_versions_raises(tmp_path: Path) -> None:
    display = PlainDisplay()

    a = tmp_path / "a"
    a.mkdir()
    _write_requirements(
        a,
        (
            "requirements:\n"
            "  - name: npx\n"
            "    servers: [context7]\n"
            "    version:\n"
            "      require: ~10.0.0\n"
        ),
    )

    b = tmp_path / "b"
    b.mkdir()
    _write_requirements(
        b,
        (
            "requirements:\n"
            "  - name: npx\n"
            "    servers: [slack]\n"
            "    version:\n"
            "      require: ^10.0.0\n"
        ),
    )

    with pytest.raises(RuntimeError, match="Requirement collision"):
        load_and_filter_requirements(
            {"a": _source("a", a), "b": _source("b", b)},
            ["a/context7", "b/slack"],
            display,
        )
