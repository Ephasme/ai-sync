from __future__ import annotations

from pathlib import Path

import pytest

from ai_sync.display import PlainDisplay
from ai_sync.planning import build_plan_context, default_plan_path, save_plan, validate_saved_plan


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
    (source_root / ".env.ai-sync.tpl").write_text("TOKEN=abc\n", encoding="utf-8")
    (source_root / "mcp-servers.yaml").write_text(
        'servers:\n  context7:\n    method: stdio\n    command: npx\n    env:\n      TOKEN: "$TOKEN"\n',
        encoding="utf-8",
    )

    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / ".gitignore").write_text(
        ".cursor/\n.codex/\n.gemini/\n.ai-sync/\n.env.ai-sync\n",
        encoding="utf-8",
    )
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


def test_build_plan_context_marks_secret_backed_outputs(tmp_path: Path) -> None:
    config_root, project_root = _write_project(tmp_path)
    display = PlainDisplay()
    context = build_plan_context(project_root, config_root, display)
    secret_targets = {action.target for action in context.plan.actions if action.secret_backed}
    assert str(project_root / ".env.ai-sync") in secret_targets


def test_saved_plan_validates_against_current_inputs(tmp_path: Path) -> None:
    config_root, project_root = _write_project(tmp_path)
    display = PlainDisplay()
    context = build_plan_context(project_root, config_root, display)
    plan_path = default_plan_path(project_root)
    save_plan(context.plan, plan_path)

    current = build_plan_context(project_root, config_root, display)
    saved = validate_saved_plan(plan_path, current.plan)
    assert saved.manifest_fingerprint == current.plan.manifest_fingerprint


def test_saved_plan_invalidates_when_manifest_changes(tmp_path: Path) -> None:
    config_root, project_root = _write_project(tmp_path)
    display = PlainDisplay()
    context = build_plan_context(project_root, config_root, display)
    plan_path = default_plan_path(project_root)
    save_plan(context.plan, plan_path)

    manifest_path = project_root / ".ai-sync.yaml"
    manifest_path.write_text(manifest_path.read_text(encoding="utf-8") + "settings:\n  mode: strict\n", encoding="utf-8")

    current = build_plan_context(project_root, config_root, display)
    with pytest.raises(RuntimeError, match="Saved plan is no longer valid"):
        validate_saved_plan(plan_path, current.plan)


def test_build_plan_context_rejects_colliding_commands(tmp_path: Path) -> None:
    config_root = tmp_path / "config"
    config_root.mkdir()
    (config_root / "config.toml").write_text('op_account = "x"\n', encoding="utf-8")

    company = tmp_path / "company"
    (company / "commands").mkdir(parents=True)
    (company / "commands" / "shared.md").write_text("Company\n", encoding="utf-8")
    frontend = tmp_path / "frontend"
    (frontend / "commands").mkdir(parents=True)
    (frontend / "commands" / "shared.md").write_text("Frontend\n", encoding="utf-8")

    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / ".gitignore").write_text(".cursor/\n.codex/\n.gemini/\n.ai-sync/\n.env.ai-sync\n", encoding="utf-8")
    (project_root / ".ai-sync.yaml").write_text(
        "\n".join(
            [
                "sources:",
                "  company:",
                f"    source: {company}",
                "  frontend:",
                f"    source: {frontend}",
                "commands:",
                "  - company/shared.md",
                "  - frontend/shared.md",
                "",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="Planning collision"):
        build_plan_context(project_root, config_root, PlainDisplay())
