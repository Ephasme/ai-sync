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
    (source_root / "prompts" / "engineer").mkdir(parents=True)
    (source_root / "prompts" / "engineer" / "artifact.yaml").write_text(
        "slug: engineer\n"
        "name: Engineer\n"
        "description: Senior software engineer assistant\n",
        encoding="utf-8",
    )
    (source_root / "prompts" / "engineer" / "prompt.md").write_text("## Task\nHelp\n", encoding="utf-8")
    (source_root / "skills" / "code-review" / "files").mkdir(parents=True)
    (source_root / "skills" / "code-review" / "artifact.yaml").write_text(
        "name: code-review\n"
        "description: Review code skill\n",
        encoding="utf-8",
    )
    (source_root / "skills" / "code-review" / "prompt.md").write_text("# Skill\n", encoding="utf-8")
    (source_root / "commands" / "session-summary").mkdir(parents=True)
    (source_root / "commands" / "session-summary" / "artifact.yaml").write_text(
        "description: Session summary command\n",
        encoding="utf-8",
    )
    (source_root / "commands" / "session-summary" / "prompt.md").write_text("Summarize\n", encoding="utf-8")
    (source_root / "rules" / "commit").mkdir(parents=True)
    (source_root / "rules" / "commit" / "artifact.yaml").write_text(
        "description: Commit conventions\n"
        "alwaysApply: true\n",
        encoding="utf-8",
    )
    (source_root / "rules" / "commit" / "prompt.md").write_text("Commit rules\n", encoding="utf-8")
    (source_root / "env.yaml").write_text("TOKEN:\n  value: abc\n", encoding="utf-8")
    (source_root / "mcp-servers" / "context7").mkdir(parents=True)
    (source_root / "mcp-servers" / "context7" / "artifact.yaml").write_text(
        'method: stdio\ncommand: npx\nenv:\n  TOKEN: "$TOKEN"\n',
        encoding="utf-8",
    )

    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / ".gitignore").write_text(
        ".cursor/\n.codex/\n.gemini/\n.claude/\n.mcp.json\nCLAUDE.md\n.ai-sync/\n.env.ai-sync\n",
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
                "  - company/session-summary",
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


def _run_apply_from_context(context, project_root, display):
    return run_apply(
        project_root=project_root,
        source_roots={alias: source.root for alias, source in context.resolved_sources.items()},
        manifest=context.manifest,
        mcp_manifest=context.mcp_manifest,
        secrets=context.secrets,
        runtime_env=context.runtime_env,
        resolved_sources=context.resolved_sources,
        display=display,
    )


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


def test_build_plan_context_targets_rule_files(tmp_path: Path) -> None:
    config_root, project_root = _write_project(tmp_path)
    display = PlainDisplay()
    context = build_plan_context(project_root, config_root, display)

    rule_targets = {action.target for action in context.plan.actions if action.kind == "rule"}
    assert rule_targets == {
        str(project_root / ".ai-sync" / "rules" / "company-commit.md"),
        str(project_root / ".claude" / "rules" / "company-commit.md"),
    }

    index_targets = {action.target for action in context.plan.actions if action.kind == "rule-index"}
    assert index_targets == {str(project_root / "AGENTS.md")}


def test_build_plan_context_hides_unchanged_managed_outputs(tmp_path: Path) -> None:
    config_root, project_root = _write_project(tmp_path)
    display = PlainDisplay()
    context = build_plan_context(project_root, config_root, display)

    assert _run_apply_from_context(context, project_root, display) == 0

    current = build_plan_context(project_root, config_root, display)
    assert current.plan.actions == []


def test_build_plan_context_only_shows_changed_rule_outputs(tmp_path: Path) -> None:
    config_root, project_root = _write_project(tmp_path)
    display = PlainDisplay()
    context = build_plan_context(project_root, config_root, display)

    assert _run_apply_from_context(context, project_root, display) == 0

    rule_path = tmp_path / "company-source" / "rules" / "commit" / "artifact.yaml"
    rule_path.write_text(
        "description: Commit conventions\n"
        "alwaysApply: true\n",
        encoding="utf-8",
    )
    rule_path.with_name("prompt.md").write_text("Updated commit rules\n", encoding="utf-8")

    current = build_plan_context(project_root, config_root, display)
    assert {action.kind for action in current.plan.actions} == {"rule"}
    assert {action.target for action in current.plan.actions} == {
        str(project_root / ".ai-sync" / "rules" / "company-commit.md"),
        str(project_root / ".claude" / "rules" / "company-commit.md"),
    }


def test_apply_writes_claude_rule_with_frontmatter_from_metadata(tmp_path: Path) -> None:
    config_root, project_root = _write_project(tmp_path)
    display = PlainDisplay()
    context = build_plan_context(project_root, config_root, display)

    assert _run_apply_from_context(context, project_root, display) == 0

    claude_rule_path = project_root / ".claude" / "rules" / "company-commit.md"
    content = claude_rule_path.read_text(encoding="utf-8")
    assert content.startswith(
        "---\n"
        'description: "Commit conventions"\n'
        "alwaysApply: true\n"
        "---\n\n"
    )
    assert content.endswith("Commit rules\n")


def test_build_plan_context_and_apply_show_and_execute_delete_for_removed_command(tmp_path: Path) -> None:
    config_root, project_root = _write_project(tmp_path)
    display = PlainDisplay()
    context = build_plan_context(project_root, config_root, display)

    assert _run_apply_from_context(context, project_root, display) == 0

    codex_command = project_root / ".codex" / "commands" / "company-session-summary.md"
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

    assert _run_apply_from_context(current, project_root, display) == 0

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


def test_saved_plan_invalidates_when_prompt_file_changes(tmp_path: Path) -> None:
    config_root, project_root = _write_project(tmp_path)
    display = PlainDisplay()
    context = build_plan_context(project_root, config_root, display)
    plan_path = default_plan_path(project_root)
    save_plan(context.plan, plan_path)

    prompt_path = tmp_path / "company-source" / "commands" / "session-summary" / "prompt.md"
    prompt_path.write_text("Summarize differently\n", encoding="utf-8")

    current = build_plan_context(project_root, config_root, display)
    with pytest.raises(RuntimeError, match="Saved plan is no longer valid"):
        validate_saved_plan(plan_path, current.plan)


def test_local_var_preserved_from_existing_env(tmp_path: Path) -> None:
    config_root, project_root = _write_project(tmp_path)
    source_root = tmp_path / "company-source"
    (source_root / "env.yaml").write_text(
        "TOKEN:\n  value: abc\nMY_PAT:\n  scope: local\n  description: personal token\n",
        encoding="utf-8",
    )

    (project_root / ".env.ai-sync").write_text("MY_PAT=my-secret-value\n", encoding="utf-8")

    display = PlainDisplay()
    context = build_plan_context(project_root, config_root, display)

    assert context.runtime_env.env["MY_PAT"] == "my-secret-value"
    assert "MY_PAT" not in context.runtime_env.unfilled_local_vars


def test_unfilled_local_var_referenced_by_mcp_raises(tmp_path: Path) -> None:
    config_root, project_root = _write_project(tmp_path)
    source_root = tmp_path / "company-source"
    (source_root / "env.yaml").write_text(
        "TOKEN:\n  scope: local\n  description: personal token\n",
        encoding="utf-8",
    )

    display = PlainDisplay()
    with pytest.raises(RuntimeError, match="local-scoped.*Set its value"):
        build_plan_context(project_root, config_root, display)


def test_unfilled_local_var_not_referenced_by_mcp_succeeds(tmp_path: Path) -> None:
    config_root, project_root = _write_project(tmp_path)
    source_root = tmp_path / "company-source"
    (source_root / "env.yaml").write_text(
        "TOKEN:\n  value: abc\nOPTIONAL_PAT:\n  scope: local\n",
        encoding="utf-8",
    )

    display = PlainDisplay()
    context = build_plan_context(project_root, config_root, display)

    assert "OPTIONAL_PAT" in context.runtime_env.unfilled_local_vars
    assert "OPTIONAL_PAT" in context.runtime_env.local_vars

    env_actions = [a for a in context.plan.actions if a.kind == "env-file"]
    assert len(env_actions) == 1


def test_build_plan_no_collision_with_alias_prefixed_commands(tmp_path: Path) -> None:
    config_root = tmp_path / "config"
    config_root.mkdir()
    (config_root / "config.toml").write_text('op_account_identifier = "x.1password.com"\n', encoding="utf-8")

    company = tmp_path / "company"
    (company / "commands" / "shared").mkdir(parents=True)
    (company / "commands" / "shared" / "artifact.yaml").write_text(
        "description: Company shared command\n",
        encoding="utf-8",
    )
    (company / "commands" / "shared" / "prompt.md").write_text("Company\n", encoding="utf-8")
    frontend = tmp_path / "frontend"
    (frontend / "commands" / "shared").mkdir(parents=True)
    (frontend / "commands" / "shared" / "artifact.yaml").write_text(
        "description: Frontend shared command\n",
        encoding="utf-8",
    )
    (frontend / "commands" / "shared" / "prompt.md").write_text("Frontend\n", encoding="utf-8")

    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / ".gitignore").write_text(
        ".cursor/\n.codex/\n.gemini/\n.claude/\n.mcp.json\nCLAUDE.md\n.ai-sync/\n.env.ai-sync\n",
        encoding="utf-8",
    )
    (project_root / ".ai-sync.yaml").write_text(
        "\n".join(
            [
                "sources:",
                "  company:",
                f"    source: {company}",
                "  frontend:",
                f"    source: {frontend}",
                "commands:",
                "  - company/shared",
                "  - frontend/shared",
                "",
            ]
        ),
        encoding="utf-8",
    )

    display = PlainDisplay()
    context = build_plan_context(project_root, config_root, display)
    command_actions = [a for a in context.plan.actions if a.kind == "command"]
    assert len(command_actions) >= 2
