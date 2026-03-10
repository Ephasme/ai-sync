from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from ai_sync import cli
from ai_sync.display import PlainDisplay
from ai_sync.gitignore import SENSITIVE_PATHS


@pytest.fixture()
def display() -> PlainDisplay:
    return PlainDisplay()


def _write_project(tmp_path: Path) -> tuple[Path, Path]:
    config_root = tmp_path / "config"
    config_root.mkdir()
    (config_root / "config.toml").write_text('op_account = "x"\n', encoding="utf-8")

    source_root = tmp_path / "company-source"
    (source_root / "prompts").mkdir(parents=True)
    (source_root / "prompts" / "engineer.md").write_text("## Task\nHelp\n", encoding="utf-8")
    (source_root / "skills" / "code-review").mkdir(parents=True)
    (source_root / "skills" / "code-review" / "SKILL.md").write_text("# Skill\n", encoding="utf-8")
    (source_root / "commands").mkdir(parents=True)
    (source_root / "commands" / "session-summary.md").write_text("Summarize\n", encoding="utf-8")
    (source_root / "rules").mkdir(parents=True)
    (source_root / "rules" / "commit.md").write_text("Commit rules\n", encoding="utf-8")
    (source_root / "mcp-servers.yaml").write_text(
        "servers:\n  context7:\n    method: stdio\n    command: npx\n",
        encoding="utf-8",
    )

    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / ".gitignore").write_text("\n".join(SENSITIVE_PATHS) + "\n", encoding="utf-8")
    (project_root / ".ai-sync.yaml").write_text(
        "\n".join(
            [
                "sources:",
                "  company:",
                f"    source: {source_root}",
                "agents:",
                "  - company/engineer",
                "skills:",
                "  - company/code-review",
                "commands:",
                "  - company/session-summary.md",
                "rules:",
                "  - company/commit",
                "mcp-servers:",
                "  - company/context7",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return config_root, project_root


def test_run_install_writes_config(monkeypatch, tmp_path: Path, display: PlainDisplay) -> None:
    monkeypatch.setattr(cli, "ensure_layout", lambda: tmp_path)
    args = argparse.Namespace(op_account="Test", force=True)
    assert cli._run_install(args, display) == 0
    assert "op_account" in (tmp_path / "config.toml").read_text(encoding="utf-8")


def test_run_install_requires_op_account(monkeypatch, tmp_path: Path, display: PlainDisplay) -> None:
    monkeypatch.setattr(cli, "ensure_layout", lambda: tmp_path)
    monkeypatch.delenv("OP_ACCOUNT", raising=False)
    monkeypatch.delenv("OP_SERVICE_ACCOUNT_TOKEN", raising=False)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    args = argparse.Namespace(op_account=None, force=True)
    assert cli._run_install(args, display) == 1


def test_run_import_local_path_links_in_place(monkeypatch, tmp_path: Path, display: PlainDisplay) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    dest = tmp_path / "dest"
    dest.mkdir()
    monkeypatch.setattr(cli, "ensure_layout", lambda: dest)
    args = argparse.Namespace(repo=str(repo), name="my-repo", force=False)
    assert cli._run_import(args, display) == 0
    assert not (dest / "repos" / "my-repo").exists()


def test_build_parser_has_plan_and_apply() -> None:
    parser = cli._build_parser()
    assert parser.parse_args(["plan"]).command == "plan"
    assert parser.parse_args(["apply"]).command == "apply"


def test_run_plan_saves_plan_file(monkeypatch, tmp_path: Path, display: PlainDisplay) -> None:
    config_root, project_root = _write_project(tmp_path)
    monkeypatch.setattr(cli, "find_project_root", lambda: project_root)
    args = argparse.Namespace(plain=True, out=None)
    assert cli._run_plan(args, config_root, display) == 0
    assert (project_root / ".ai-sync" / "last-plan.yaml").exists()


def test_run_apply_uses_saved_plan_when_provided(monkeypatch, tmp_path: Path, display: PlainDisplay) -> None:
    config_root, project_root = _write_project(tmp_path)
    monkeypatch.setattr(cli, "find_project_root", lambda: project_root)
    assert cli._run_plan(argparse.Namespace(plain=True, out=None), config_root, display) == 0

    captured: dict[str, object] = {}

    def _fake_run_apply(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(cli, "run_apply", _fake_run_apply)
    args = argparse.Namespace(plain=True, planfile=str(project_root / ".ai-sync" / "last-plan.yaml"))
    assert cli._run_apply(args, config_root, display) == 0
    assert "source_roots" in captured


def test_run_apply_without_plan_builds_fresh_plan(monkeypatch, tmp_path: Path, display: PlainDisplay) -> None:
    config_root, project_root = _write_project(tmp_path)
    monkeypatch.setattr(cli, "find_project_root", lambda: project_root)

    captured: dict[str, object] = {}

    def _fake_run_apply(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(cli, "run_apply", _fake_run_apply)
    args = argparse.Namespace(plain=True, planfile=None)
    assert cli._run_apply(args, config_root, display) == 0
    assert "manifest" in captured


def test_run_init_is_deprecated(tmp_path: Path, display: PlainDisplay) -> None:
    assert cli._run_init(argparse.Namespace(tag=None), tmp_path, display) == 1
