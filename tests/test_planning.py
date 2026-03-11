from __future__ import annotations

from pathlib import Path

import pytest

from ai_sync.display import PlainDisplay
from ai_sync.planning import build_plan_context, default_plan_path, save_plan, validate_saved_plan
from ai_sync.project import manifest_fingerprint
from ai_sync.sync_runner import run_apply


def _write_project(tmp_path: Path) -> tuple[Path, Path]:
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
    (source_root / ".env.ai-sync.tpl").write_text("TOKEN=abc\n", encoding="utf-8")
    (source_root / "mcp-servers" / "context7").mkdir(parents=True)
    (source_root / "mcp-servers" / "context7" / "server.yaml").write_text(
        'method: stdio\ncommand: npx\nenv:\n  TOKEN: "$TOKEN"\n',
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


def test_build_plan_context_prefers_local_manifest(tmp_path: Path) -> None:
    config_root, project_root = _write_project(tmp_path)
    local_manifest_path = project_root / ".ai-sync.local.yaml"
    local_manifest_path.write_text("sources: {}\n", encoding="utf-8")

    display = PlainDisplay()
    context = build_plan_context(project_root, config_root, display)

    assert context.manifest.agents == []
    assert context.plan.manifest_path == str(local_manifest_path)
    assert context.plan.manifest_fingerprint == manifest_fingerprint(local_manifest_path)


def test_build_plan_context_targets_generated_rules_file(tmp_path: Path) -> None:
    config_root, project_root = _write_project(tmp_path)
    display = PlainDisplay()
    context = build_plan_context(project_root, config_root, display)

    rule_targets = {action.target for action in context.plan.actions if action.kind == "rule"}
    assert rule_targets == {str(project_root / "AGENTS.generated.md")}

    link_targets = {action.target for action in context.plan.actions if action.kind == "rule-link"}
    assert link_targets == {str(project_root / "AGENTS.md")}


def test_build_plan_context_hides_unchanged_managed_outputs(tmp_path: Path) -> None:
    config_root, project_root = _write_project(tmp_path)
    display = PlainDisplay()
    context = build_plan_context(project_root, config_root, display)

    assert run_apply(
        project_root=project_root,
        source_roots={alias: source.root for alias, source in context.resolved_sources.items()},
        manifest=context.manifest,
        mcp_manifest=context.mcp_manifest,
        secrets=context.secrets,
        runtime_env=context.runtime_env,
        display=display,
    ) == 0

    current = build_plan_context(project_root, config_root, display)
    assert current.plan.actions == []


def test_build_plan_context_only_shows_changed_rule_outputs(tmp_path: Path) -> None:
    config_root, project_root = _write_project(tmp_path)
    display = PlainDisplay()
    context = build_plan_context(project_root, config_root, display)

    assert run_apply(
        project_root=project_root,
        source_roots={alias: source.root for alias, source in context.resolved_sources.items()},
        manifest=context.manifest,
        mcp_manifest=context.mcp_manifest,
        secrets=context.secrets,
        runtime_env=context.runtime_env,
        display=display,
    ) == 0

    rule_path = tmp_path / "company-source" / "rules" / "commit.md"
    rule_path.write_text("Updated commit rules\n", encoding="utf-8")

    current = build_plan_context(project_root, config_root, display)
    assert {action.kind for action in current.plan.actions} == {"rule"}
    assert {action.target for action in current.plan.actions} == {str(project_root / "AGENTS.generated.md")}


def test_build_plan_context_and_apply_show_and_execute_delete_for_removed_command(tmp_path: Path) -> None:
    config_root, project_root = _write_project(tmp_path)
    display = PlainDisplay()
    context = build_plan_context(project_root, config_root, display)

    assert run_apply(
        project_root=project_root,
        source_roots={alias: source.root for alias, source in context.resolved_sources.items()},
        manifest=context.manifest,
        mcp_manifest=context.mcp_manifest,
        secrets=context.secrets,
        runtime_env=context.runtime_env,
        display=display,
    ) == 0

    codex_command = project_root / ".codex" / "commands" / "session-summary.md"
    assert codex_command.exists()

    manifest_path = project_root / ".ai-sync.yaml"
    manifest_path.write_text(
        "\n".join(
            [
                "sources:",
                "  company:",
                f"    source: {tmp_path / 'company-source'}",
                "agents:",
                "  - company/engineer",
                "skills:",
                "  - company/code-review",
                "rules:",
                "  - company/commit",
                "mcp-servers:",
                "  - company/context7",
                "",
            ]
        ),
        encoding="utf-8",
    )

    current = build_plan_context(project_root, config_root, display)
    delete_actions = [action for action in current.plan.actions if action.action == "delete"]
    assert any(action.kind == "command" for action in delete_actions)

    assert run_apply(
        project_root=project_root,
        source_roots={alias: source.root for alias, source in current.resolved_sources.items()},
        manifest=current.manifest,
        mcp_manifest=current.mcp_manifest,
        secrets=current.secrets,
        runtime_env=current.runtime_env,
        display=display,
    ) == 0

    assert not codex_command.exists()


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
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8") + "settings:\n  mode: strict\n",
        encoding="utf-8",
    )

    current = build_plan_context(project_root, config_root, display)
    with pytest.raises(RuntimeError, match="Saved plan is no longer valid"):
        validate_saved_plan(plan_path, current.plan)


def test_build_plan_context_rejects_colliding_commands(tmp_path: Path) -> None:
    config_root = tmp_path / "config"
    config_root.mkdir()
    (config_root / "config.toml").write_text('op_account_identifier = "x.1password.com"\n', encoding="utf-8")

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
