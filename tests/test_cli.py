from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_sync import cli, command_handlers
from ai_sync.display import PlainDisplay
from ai_sync.gitignore import SENSITIVE_PATHS
from ai_sync.planning import PlanAction


class TTYStringIO(StringIO):
    def isatty(self) -> bool:
        return True


@pytest.fixture()
def display() -> PlainDisplay:
    return PlainDisplay()


def _write_project(tmp_path: Path, *, with_gitignore: bool = True) -> tuple[Path, Path]:
    config_root = tmp_path / "config"
    config_root.mkdir()
    (config_root / "config.toml").write_text('op_account_identifier = "x.1password.com"\n', encoding="utf-8")

    source_root = tmp_path / "company-source"
    (source_root / "prompts").mkdir(parents=True)
    (source_root / "prompts" / "engineer.md").write_text("## Task\nHelp\n", encoding="utf-8")
    (source_root / "skills" / "code-review").mkdir(parents=True)
    (source_root / "skills" / "code-review" / "SKILL.md").write_text("# Skill\n", encoding="utf-8")
    (source_root / "commands").mkdir(parents=True)
    (source_root / "commands" / "session-summary.md").write_text("Summarize\n", encoding="utf-8")
    (source_root / "rules").mkdir(parents=True)
    (source_root / "rules" / "commit.md").write_text("Commit rules\n", encoding="utf-8")
    (source_root / "mcp-servers" / "context7").mkdir(parents=True)
    (source_root / "mcp-servers" / "context7" / "server.yaml").write_text(
        "method: stdio\ncommand: npx\n",
        encoding="utf-8",
    )

    project_root = tmp_path / "project"
    project_root.mkdir()
    if with_gitignore:
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
    monkeypatch.setattr(command_handlers, "ensure_layout", lambda: tmp_path)
    assert (
        command_handlers.run_install_command(
            display=display,
            op_account_identifier="example.1password.com",
            force=True,
        )
        == 0
    )
    assert "op_account_identifier" in (tmp_path / "config.toml").read_text(encoding="utf-8")


def test_run_install_requires_op_account_identifier(monkeypatch, tmp_path: Path, display: PlainDisplay) -> None:
    monkeypatch.setattr(command_handlers, "ensure_layout", lambda: tmp_path)
    stdin = StringIO()
    assert (
        command_handlers.run_install_command(
            display=display,
            op_account_identifier=None,
            force=True,
            environ={},
            stdin=stdin,
        )
        == 1
    )


def test_build_parser_has_plan_and_apply() -> None:
    parser = cli._build_parser()
    assert parser.parse_args(["plan"]).command == "plan"
    assert parser.parse_args(["apply"]).command == "apply"


def test_build_parser_accepts_op_account_identifier_flag() -> None:
    parser = cli._build_parser()
    args = parser.parse_args(["install", "--op-account-identifier", "example.1password.com"])
    assert args.command == "install"
    assert args.op_account_identifier == "example.1password.com"


def test_run_plan_saves_plan_file(monkeypatch, tmp_path: Path, display: PlainDisplay) -> None:
    config_root, project_root = _write_project(tmp_path)
    monkeypatch.setattr(command_handlers, "find_project_root", lambda: project_root)
    assert command_handlers.run_plan_command(config_root=config_root, display=display, out=None) == 0
    assert (project_root / ".ai-sync" / "last-plan.yaml").exists()


def test_run_plan_without_gitignore_still_succeeds(monkeypatch, tmp_path: Path, display: PlainDisplay) -> None:
    config_root, project_root = _write_project(tmp_path, with_gitignore=False)
    monkeypatch.setattr(command_handlers, "find_project_root", lambda: project_root)
    assert command_handlers.run_plan_command(config_root=config_root, display=display, out=None) == 0
    assert (project_root / ".ai-sync" / "last-plan.yaml").exists()


def test_run_apply_uses_saved_plan_when_provided(monkeypatch, tmp_path: Path, display: PlainDisplay) -> None:
    config_root, project_root = _write_project(tmp_path)
    monkeypatch.setattr(command_handlers, "find_project_root", lambda: project_root)
    assert command_handlers.run_plan_command(config_root=config_root, display=display, out=None) == 0

    captured: dict[str, object] = {}

    def _fake_run_apply(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(command_handlers, "run_apply", _fake_run_apply)
    assert (
        command_handlers.run_apply_command(
            config_root=config_root,
            display=display,
            planfile=str(project_root / ".ai-sync" / "last-plan.yaml"),
        )
        == 0
    )
    assert "source_roots" in captured


def test_run_apply_without_plan_builds_fresh_plan(monkeypatch, tmp_path: Path, display: PlainDisplay) -> None:
    config_root, project_root = _write_project(tmp_path)
    monkeypatch.setattr(command_handlers, "find_project_root", lambda: project_root)

    captured: dict[str, object] = {}

    def _fake_run_apply(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(command_handlers, "run_apply", _fake_run_apply)
    assert command_handlers.run_apply_command(config_root=config_root, display=display, planfile=None) == 0
    assert "manifest" in captured


def test_run_apply_without_gitignore_still_succeeds(monkeypatch, tmp_path: Path, display: PlainDisplay) -> None:
    config_root, project_root = _write_project(tmp_path, with_gitignore=False)
    monkeypatch.setattr(command_handlers, "find_project_root", lambda: project_root)

    captured: dict[str, object] = {}

    def _fake_run_apply(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(command_handlers, "run_apply", _fake_run_apply)
    assert command_handlers.run_apply_command(config_root=config_root, display=display, planfile=None) == 0
    assert "manifest" in captured


def test_run_apply_prints_plan_and_not_legacy_sync_sections(
    monkeypatch, tmp_path: Path, display: PlainDisplay, capsys
) -> None:
    config_root, project_root = _write_project(tmp_path)
    monkeypatch.setattr(command_handlers, "find_project_root", lambda: project_root)

    assert command_handlers.run_apply_command(config_root=config_root, display=display, planfile=None) == 0

    out = capsys.readouterr().out
    assert "Planned Actions" in out
    assert "Syncing Agents" not in out
    assert "Syncing Skills" not in out


def test_run_apply_without_project_mentions_both_manifest_names(
    monkeypatch, tmp_path: Path, display: PlainDisplay, capsys
) -> None:
    config_root, _project_root = _write_project(tmp_path)
    monkeypatch.setattr(command_handlers, "find_project_root", lambda: None)

    assert command_handlers.run_apply_command(config_root=config_root, display=display, planfile=None) == 1

    out = capsys.readouterr().out
    assert "No .ai-sync.local.yaml or .ai-sync.yaml found. Create one first." in out


def test_run_doctor_without_project_mentions_both_manifest_names(
    monkeypatch, tmp_path: Path, display: PlainDisplay, capsys
) -> None:
    config_root, _project_root = _write_project(tmp_path)
    monkeypatch.setattr(command_handlers, "find_project_root", lambda: None)

    assert command_handlers.run_doctor_command(config_root=config_root, display=display) == 0

    out = capsys.readouterr().out
    assert "No project found (no .ai-sync.local.yaml or .ai-sync.yaml in current directory tree)" in out


def test_run_doctor_reports_local_manifest_name(monkeypatch, tmp_path: Path, display: PlainDisplay, capsys) -> None:
    config_root, project_root = _write_project(tmp_path)
    (project_root / ".ai-sync.local.yaml").write_text("sources: {}\n", encoding="utf-8")
    monkeypatch.setattr(command_handlers, "find_project_root", lambda: project_root)

    assert command_handlers.run_doctor_command(config_root=config_root, display=display) == 0

    out = capsys.readouterr().out
    assert ".ai-sync.local.yaml: OK (0 sources declared)" in out


def test_run_uninstall_without_project_mentions_both_manifest_names(
    monkeypatch, display: PlainDisplay, capsys
) -> None:
    monkeypatch.setattr(command_handlers, "find_project_root", lambda: None)

    assert command_handlers.run_uninstall_command(display=display, apply=False) == 1

    out = capsys.readouterr().out
    assert "No .ai-sync.local.yaml or .ai-sync.yaml found. Nothing to uninstall." in out


def test_confirm_plan_deletions_accepts_yes(display: PlainDisplay) -> None:
    plan = SimpleNamespace(
        actions=[
            PlanAction(
                action="delete",
                source_alias="company",
                kind="skill",
                resource="company/code-review",
                target="/tmp/skill",
                target_key="/tmp/skill",
            )
        ]
    )
    stdin = TTYStringIO()
    assert (
        command_handlers._confirm_plan_deletions(
            plan,
            display,
            stdin=stdin,
            prompt_input=lambda _prompt: "y",
        )
        is True
    )


def test_confirm_plan_deletions_rejects_no(display: PlainDisplay) -> None:
    plan = SimpleNamespace(
        actions=[
            PlanAction(
                action="delete",
                source_alias="company",
                kind="skill",
                resource="company/code-review",
                target="/tmp/skill",
                target_key="/tmp/skill",
            )
        ]
    )
    stdin = TTYStringIO()
    assert (
        command_handlers._confirm_plan_deletions(
            plan,
            display,
            stdin=stdin,
            prompt_input=lambda _prompt: "n",
        )
        is False
    )


def test_confirm_plan_deletions_rejects_non_interactive(display: PlainDisplay) -> None:
    plan = SimpleNamespace(
        actions=[
            PlanAction(
                action="delete",
                source_alias="company",
                kind="skill",
                resource="company/code-review",
                target="/tmp/skill",
                target_key="/tmp/skill",
            )
        ]
    )
    stdin = StringIO()
    assert (
        command_handlers._confirm_plan_deletions(
            plan,
            display,
            stdin=stdin,
            prompt_input=lambda _prompt: "y",
        )
        is False
    )
