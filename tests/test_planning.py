from __future__ import annotations

from pathlib import Path

import pytest

from ai_sync.data_classes.effect_spec import EffectSpec
from ai_sync.data_classes.write_spec import WriteSpec
from ai_sync.di import create_container
from ai_sync.services.plan_persistence_service import PlanPersistenceService
from ai_sync.services.plain_display_service import PlainDisplayService
from ai_sync.services.project_manifest_service import ProjectManifestService

PLAN_PERSISTENCE = PlanPersistenceService()


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
        "name: Session summary\n"
        "description: Session summary command\n",
        encoding="utf-8",
    )
    (source_root / "commands" / "session-summary" / "prompt.md").write_text("Summarize\n", encoding="utf-8")
    (source_root / "rules" / "commit").mkdir(parents=True)
    (source_root / "rules" / "commit" / "artifact.yaml").write_text(
        "name: Commit conventions\n"
        "description: Commit conventions\n"
        "alwaysApply: true\n",
        encoding="utf-8",
    )
    (source_root / "rules" / "commit" / "prompt.md").write_text("Commit rules\n", encoding="utf-8")
    (source_root / "mcp-servers" / "context7").mkdir(parents=True)
    (source_root / "mcp-servers" / "context7" / "artifact.yaml").write_text(
        "name: Context7\n"
        "description: Library documentation lookup via Context7.\n"
        "method: stdio\n"
        "command: npx\n"
        "dependencies:\n"
        "  env:\n"
        "    TOKEN: abc\n",
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
    container = create_container()
    return container.apply_service().run_apply(
        project_root=project_root,
        resolved_artifacts=context.resolved_artifacts,
        display=display,
    )


def _build_plan_context(project_root: Path, config_root: Path, display: PlainDisplayService):
    container = create_container()
    return container.plan_service().assemble_plan_context(project_root, config_root, display)


def test_build_plan_context_does_not_mark_literal_only_mcp_env_secret_backed(tmp_path: Path) -> None:
    config_root, project_root = _write_project(tmp_path)
    display = PlainDisplayService()
    context = _build_plan_context(project_root, config_root, display)
    secret_targets = {action.target for action in context.plan.actions if action.secret_backed}
    assert str(project_root / ".env.ai-sync") not in secret_targets
    assert str(project_root / ".cursor" / "mcp.json") not in secret_targets


def test_build_plan_context_strips_dependency_metadata_from_rendered_mcp_outputs(
    tmp_path: Path,
) -> None:
    config_root, project_root = _write_project(tmp_path)
    display = PlainDisplayService()
    context = _build_plan_context(project_root, config_root, display)
    mcp_entries = [
        (artifact, specs)
        for artifact, specs in context.resolved_artifacts.entries
        if artifact.kind == "mcp-server"
    ]
    assert mcp_entries
    for _artifact, specs in mcp_entries:
        for spec in specs:
            assert isinstance(spec, WriteSpec)
            assert "dependencies" not in str(spec.value)


def test_build_plan_context_synthesizes_mcp_env_from_dependencies(tmp_path: Path) -> None:
    config_root, project_root = _write_project(tmp_path)
    display = PlainDisplayService()
    context = _build_plan_context(project_root, config_root, display)

    mcp_entries = [
        (artifact, specs)
        for artifact, specs in context.resolved_artifacts.entries
        if artifact.kind == "mcp-server"
    ]
    assert mcp_entries
    for artifact, specs in mcp_entries:
        assert artifact.env_dependencies["TOKEN"].literal == "abc"
        for spec in specs:
            assert isinstance(spec, WriteSpec)
            assert isinstance(spec.value, dict)
            assert spec.value["env"] == {"TOKEN": "abc"}


def test_build_plan_context_includes_artifact_names_and_descriptions(tmp_path: Path) -> None:
    config_root, project_root = _write_project(tmp_path)
    display = PlainDisplayService()
    context = _build_plan_context(project_root, config_root, display)

    actions_by_kind = {action.kind: action for action in context.plan.actions}
    assert actions_by_kind["command"].name == "Session summary"
    assert actions_by_kind["command"].description == "Session summary command"
    assert actions_by_kind["rule"].name == "Commit conventions"
    assert actions_by_kind["mcp-server"].name == "Context7"
    assert (
        actions_by_kind["mcp-server"].description
        == "Library documentation lookup via Context7."
    )


def test_build_plan_context_prefers_local_manifest(tmp_path: Path) -> None:
    config_root, project_root = _write_project(tmp_path)
    local_manifest_path = project_root / ".ai-sync.local.yaml"
    local_manifest_path.write_text("sources: {}\n", encoding="utf-8")

    display = PlainDisplayService()
    context = _build_plan_context(project_root, config_root, display)

    assert context.manifest.agents == []
    assert context.plan.manifest_path == str(local_manifest_path)
    assert context.plan.manifest_fingerprint == ProjectManifestService().manifest_fingerprint(
        local_manifest_path
    )


def test_build_plan_context_targets_rule_files(tmp_path: Path) -> None:
    config_root, project_root = _write_project(tmp_path)
    display = PlainDisplayService()
    context = _build_plan_context(project_root, config_root, display)

    rule_targets = {action.target for action in context.plan.actions if action.kind == "rule"}
    assert rule_targets == {
        str(project_root / ".ai-sync" / "rules" / "company-commit.md"),
        str(project_root / ".claude" / "rules" / "company-commit.md"),
    }

    index_targets = {action.target for action in context.plan.actions if action.kind == "rule-index"}
    assert index_targets == {str(project_root / "AGENTS.md")}


def test_build_plan_context_hides_unchanged_managed_outputs(tmp_path: Path) -> None:
    config_root, project_root = _write_project(tmp_path)
    display = PlainDisplayService()
    context = _build_plan_context(project_root, config_root, display)

    assert _run_apply_from_context(context, project_root, display) == 0

    current = _build_plan_context(project_root, config_root, display)
    assert current.plan.actions == []


def test_build_plan_context_only_shows_changed_rule_outputs(tmp_path: Path) -> None:
    config_root, project_root = _write_project(tmp_path)
    display = PlainDisplayService()
    context = _build_plan_context(project_root, config_root, display)

    assert _run_apply_from_context(context, project_root, display) == 0

    rule_path = tmp_path / "company-source" / "rules" / "commit" / "artifact.yaml"
    rule_path.write_text(
        "name: Commit conventions\n"
        "description: Commit conventions\n"
        "alwaysApply: true\n",
        encoding="utf-8",
    )
    rule_path.with_name("prompt.md").write_text("Updated commit rules\n", encoding="utf-8")

    current = _build_plan_context(project_root, config_root, display)
    assert {action.kind for action in current.plan.actions} == {"rule"}
    assert {action.target for action in current.plan.actions} == {
        str(project_root / ".ai-sync" / "rules" / "company-commit.md"),
        str(project_root / ".claude" / "rules" / "company-commit.md"),
    }


def test_apply_writes_claude_rule_with_frontmatter_from_metadata(tmp_path: Path) -> None:
    config_root, project_root = _write_project(tmp_path)
    display = PlainDisplayService()
    context = _build_plan_context(project_root, config_root, display)

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
    display = PlainDisplayService()
    context = _build_plan_context(project_root, config_root, display)

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

    current = _build_plan_context(project_root, config_root, display)
    delete_actions = [action for action in current.plan.actions if action.action == "delete"]
    assert any(action.kind == "command" for action in delete_actions)

    assert _run_apply_from_context(current, project_root, display) == 0

    assert not codex_command.exists()


def test_saved_plan_validates_against_current_inputs(tmp_path: Path) -> None:
    config_root, project_root = _write_project(tmp_path)
    display = PlainDisplayService()
    context = _build_plan_context(project_root, config_root, display)
    plan_path = PLAN_PERSISTENCE.default_plan_path(project_root)
    PLAN_PERSISTENCE.save_plan(context.plan, plan_path)

    current = _build_plan_context(project_root, config_root, display)
    saved = PLAN_PERSISTENCE.validate_saved_plan(plan_path, current.plan)
    assert saved.manifest_fingerprint == current.plan.manifest_fingerprint


def test_saved_plan_invalidates_when_manifest_changes(tmp_path: Path) -> None:
    config_root, project_root = _write_project(tmp_path)
    display = PlainDisplayService()
    context = _build_plan_context(project_root, config_root, display)
    plan_path = PLAN_PERSISTENCE.default_plan_path(project_root)
    PLAN_PERSISTENCE.save_plan(context.plan, plan_path)

    manifest_path = project_root / ".ai-sync.yaml"
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8") + "settings:\n  mode: strict\n",
        encoding="utf-8",
    )

    current = _build_plan_context(project_root, config_root, display)
    with pytest.raises(RuntimeError, match="Saved plan is no longer valid"):
        PLAN_PERSISTENCE.validate_saved_plan(plan_path, current.plan)


def test_saved_plan_invalidates_when_prompt_file_changes(tmp_path: Path) -> None:
    config_root, project_root = _write_project(tmp_path)
    display = PlainDisplayService()
    context = _build_plan_context(project_root, config_root, display)
    plan_path = PLAN_PERSISTENCE.default_plan_path(project_root)
    PLAN_PERSISTENCE.save_plan(context.plan, plan_path)

    prompt_path = tmp_path / "company-source" / "commands" / "session-summary" / "prompt.md"
    prompt_path.write_text("Summarize differently\n", encoding="utf-8")

    current = _build_plan_context(project_root, config_root, display)
    with pytest.raises(RuntimeError, match="Saved plan is no longer valid"):
        PLAN_PERSISTENCE.validate_saved_plan(plan_path, current.plan)


def test_local_var_preserved_from_existing_env(tmp_path: Path) -> None:
    config_root, project_root = _write_project(tmp_path)
    source_root = tmp_path / "company-source"
    (source_root / "mcp-servers" / "context7" / "artifact.yaml").write_text(
        "name: Context7\n"
        "description: Library documentation lookup via Context7.\n"
        "method: stdio\n"
        "command: npx\n"
        "dependencies:\n"
        "  env:\n"
        "    TOKEN: abc\n"
        "    MY_PAT:\n"
        "      local: {}\n"
        "      description: personal token\n",
        encoding="utf-8",
    )

    (project_root / ".env.ai-sync").write_text("MY_PAT=my-secret-value\n", encoding="utf-8")

    display = PlainDisplayService()
    context = _build_plan_context(project_root, config_root, display)

    assert context.runtime_env.env["MY_PAT"] == "my-secret-value"
    assert "MY_PAT" not in context.runtime_env.unfilled_local_vars


def test_unfilled_local_var_referenced_by_mcp_raises(tmp_path: Path) -> None:
    config_root, project_root = _write_project(tmp_path)
    source_root = tmp_path / "company-source"
    (source_root / "mcp-servers" / "context7" / "artifact.yaml").write_text(
        "name: Context7\n"
        "description: Library documentation lookup via Context7.\n"
        "method: stdio\n"
        "command: npx\n"
        "dependencies:\n"
        "  env:\n"
        "    TOKEN:\n"
        "      local: {}\n"
        "      description: personal token\n",
        encoding="utf-8",
    )

    display = PlainDisplayService()
    with pytest.raises(RuntimeError, match="local-scoped.*Set its value"):
        _build_plan_context(project_root, config_root, display)


def test_unfilled_local_var_not_referenced_by_mcp_succeeds(tmp_path: Path) -> None:
    config_root, project_root = _write_project(tmp_path)
    source_root = tmp_path / "company-source"
    (source_root / "commands" / "session-summary" / "artifact.yaml").write_text(
        "name: Session summary\n"
        "description: Session summary command\n"
        "dependencies:\n"
        "  env:\n"
        "    OPTIONAL_PAT:\n"
        "      local: {}\n",
        encoding="utf-8",
    )

    display = PlainDisplayService()
    context = _build_plan_context(project_root, config_root, display)

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
        "name: Shared\n"
        "description: Company shared command\n",
        encoding="utf-8",
    )
    (company / "commands" / "shared" / "prompt.md").write_text("Company\n", encoding="utf-8")
    frontend = tmp_path / "frontend"
    (frontend / "commands" / "shared").mkdir(parents=True)
    (frontend / "commands" / "shared" / "artifact.yaml").write_text(
        "name: Shared\n"
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

    display = PlainDisplayService()
    context = _build_plan_context(project_root, config_root, display)
    command_actions = [a for a in context.plan.actions if a.kind == "command"]
    assert len(command_actions) >= 2


def test_identical_duplicate_env_dependencies_merge_successfully(tmp_path: Path) -> None:
    config_root = tmp_path / "config"
    config_root.mkdir()
    (config_root / "config.toml").write_text('op_account_identifier = "x.1password.com"\n', encoding="utf-8")

    company = tmp_path / "company"
    (company / "commands" / "shared").mkdir(parents=True)
    (company / "commands" / "shared" / "artifact.yaml").write_text(
        "name: Shared\n"
        "description: Shared command\n"
        "dependencies:\n"
        "  env:\n"
        "    API_REGION: eu-west-3\n",
        encoding="utf-8",
    )
    (company / "commands" / "shared" / "prompt.md").write_text("Company\n", encoding="utf-8")

    frontend = tmp_path / "frontend"
    (frontend / "commands" / "shared").mkdir(parents=True)
    (frontend / "commands" / "shared" / "artifact.yaml").write_text(
        "name: Shared\n"
        "description: Shared command\n"
        "dependencies:\n"
        "  env:\n"
        "    API_REGION: eu-west-3\n",
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

    display = PlainDisplayService()
    context = _build_plan_context(project_root, config_root, display)
    assert context.runtime_env.env["API_REGION"] == "eu-west-3"


def test_conflicting_duplicate_env_dependencies_still_fail(tmp_path: Path) -> None:
    config_root = tmp_path / "config"
    config_root.mkdir()
    (config_root / "config.toml").write_text('op_account_identifier = "x.1password.com"\n', encoding="utf-8")

    company = tmp_path / "company"
    (company / "commands" / "shared").mkdir(parents=True)
    (company / "commands" / "shared" / "artifact.yaml").write_text(
        "name: Shared\n"
        "description: Shared command\n"
        "dependencies:\n"
        "  env:\n"
        "    API_REGION: eu-west-3\n",
        encoding="utf-8",
    )
    (company / "commands" / "shared" / "prompt.md").write_text("Company\n", encoding="utf-8")

    frontend = tmp_path / "frontend"
    (frontend / "commands" / "shared").mkdir(parents=True)
    (frontend / "commands" / "shared" / "artifact.yaml").write_text(
        "name: Shared\n"
        "description: Shared command\n"
        "dependencies:\n"
        "  env:\n"
        "    API_REGION: us-east-1\n",
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

    display = PlainDisplayService()
    with pytest.raises(RuntimeError, match="Conflicting env dependency declarations"):
        _build_plan_context(project_root, config_root, display)


def test_plan_classify_effect_pre_commit_hook_install_when_missing(tmp_path: Path) -> None:
    container = create_container()
    svc = container.plan_builder_service()
    effect = EffectSpec(
        effect_type="pre-commit-hook-install",
        target=".git/hooks/pre-commit",
        target_key="git-safety:pre-commit-hook",
    )
    assert svc._classify_effect(tmp_path, effect) == "create"


def test_plan_classify_effect_pre_commit_hook_remove_when_missing(tmp_path: Path) -> None:
    container = create_container()
    svc = container.plan_builder_service()
    effect = EffectSpec(
        effect_type="pre-commit-hook-remove",
        target=".git/hooks/pre-commit",
        target_key="git-safety:pre-commit-hook",
    )
    assert svc._classify_effect(tmp_path, effect) == "unchanged"


def test_plan_classify_effect_chmod_when_file_exists(tmp_path: Path) -> None:
    file = tmp_path / "test.json"
    file.write_text("{}", encoding="utf-8")
    container = create_container()
    svc = container.plan_builder_service()
    effect = EffectSpec(
        effect_type="chmod",
        target=str(file),
        target_key=f"chmod:{file}",
        params={"path": str(file)},
    )
    assert svc._classify_effect(tmp_path, effect) == "update"


def test_plan_classify_effect_chmod_when_file_missing(tmp_path: Path) -> None:
    file = tmp_path / "test.json"
    container = create_container()
    svc = container.plan_builder_service()
    effect = EffectSpec(
        effect_type="chmod",
        target=str(file),
        target_key=f"chmod:{file}",
        params={"path": str(file)},
    )
    assert svc._classify_effect(tmp_path, effect) == "unchanged"
