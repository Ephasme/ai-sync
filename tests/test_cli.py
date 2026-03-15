from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from dependency_injector import providers
from fastapi import FastAPI

from ai_sync import cli
from ai_sync.di import create_container
from ai_sync.models import ApplyPlan, PlanAction
from ai_sync.services.config_store_service import ConfigStoreService
from ai_sync.services.git_safety_service import SENSITIVE_PATHS
from ai_sync.services.plain_display_service import PlainDisplayService


class TTYStringIO(StringIO):
    def isatty(self) -> bool:
        return True


@pytest.fixture()
def display() -> PlainDisplayService:
    return PlainDisplayService()


def _write_project(tmp_path: Path, *, with_gitignore: bool = True) -> tuple[Path, Path]:
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
        "command: npx\n",
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


class _FixedConfigStoreService(ConfigStoreService):
    def __init__(self, root: Path) -> None:
        super().__init__()
        self._root = root

    def get_config_root(self) -> Path:
        return self._root


class _FixedProjectLocatorService:
    def __init__(self, root: Path | None) -> None:
        self._root = root

    def find_project_root(self, start: Path | None = None) -> Path | None:
        return self._root


def test_run_install_writes_config(tmp_path: Path, display: PlainDisplayService) -> None:
    container = create_container()
    container.override_providers(config_store_service=providers.Object(_FixedConfigStoreService(tmp_path)))
    service = container.install_service()
    assert (
        service.run(
            display=display,
            op_account_identifier="example.1password.com",
            force=True,
        )
        == 0
    )
    assert "op_account_identifier" in (tmp_path / "config.toml").read_text(encoding="utf-8")


def test_run_install_requires_op_account_identifier(
    tmp_path: Path, display: PlainDisplayService
) -> None:
    stdin = StringIO()
    container = create_container(environ={}, stdin=stdin)
    container.override_providers(config_store_service=providers.Object(_FixedConfigStoreService(tmp_path)))
    service = container.install_service()
    assert (
        service.run(
            display=display,
            op_account_identifier=None,
            force=True,
        )
        == 1
    )


def test_build_parser_has_plan_apply_and_ui() -> None:
    parser = cli._build_parser()
    assert parser.parse_args(["plan"]).command == "plan"
    assert parser.parse_args(["apply"]).command == "apply"
    assert parser.parse_args(["ui"]).command == "ui"


def test_build_parser_accepts_ui_host_and_port() -> None:
    parser = cli._build_parser()
    args = parser.parse_args(["ui", "--host", "0.0.0.0", "--port", "9999"])
    assert args.command == "ui"
    assert args.host == "0.0.0.0"
    assert args.port == 9999


def test_build_parser_accepts_op_account_identifier_flag() -> None:
    parser = cli._build_parser()
    args = parser.parse_args(["install", "--op-account-identifier", "example.1password.com"])
    assert args.command == "install"
    assert args.op_account_identifier == "example.1password.com"


def test_run_plan_saves_plan_file(tmp_path: Path, display: PlainDisplayService) -> None:
    config_root, project_root = _write_project(tmp_path)
    container = create_container()
    container.override_providers(
        project_locator_service=providers.Object(_FixedProjectLocatorService(project_root))
    )
    service = container.plan_service()
    assert service.run(config_root=config_root, display=display, out=None) == 0
    assert (project_root / ".ai-sync" / "last-plan.yaml").exists()


def test_run_plan_without_gitignore_still_succeeds(
    tmp_path: Path, display: PlainDisplayService
) -> None:
    config_root, project_root = _write_project(tmp_path, with_gitignore=False)
    container = create_container()
    container.override_providers(
        project_locator_service=providers.Object(_FixedProjectLocatorService(project_root))
    )
    service = container.plan_service()
    assert service.run(config_root=config_root, display=display, out=None) == 0
    assert (project_root / ".ai-sync" / "last-plan.yaml").exists()


def test_run_apply_uses_saved_plan_when_provided(
    tmp_path: Path, display: PlainDisplayService
) -> None:
    config_root, project_root = _write_project(tmp_path)
    container = create_container()
    container.override_providers(
        project_locator_service=providers.Object(_FixedProjectLocatorService(project_root))
    )
    assert container.plan_service().run(config_root=config_root, display=display, out=None) == 0

    assert (
        container.apply_service().run(
            config_root=config_root,
            display=display,
            planfile=str(project_root / ".ai-sync" / "last-plan.yaml"),
        )
        == 0
    )


def test_run_apply_without_plan_builds_fresh_plan(
    tmp_path: Path, display: PlainDisplayService
) -> None:
    config_root, project_root = _write_project(tmp_path)
    container = create_container()
    container.override_providers(
        project_locator_service=providers.Object(_FixedProjectLocatorService(project_root))
    )
    assert container.apply_service().run(config_root=config_root, display=display, planfile=None) == 0


def test_run_apply_without_gitignore_still_succeeds(
    tmp_path: Path, display: PlainDisplayService
) -> None:
    config_root, project_root = _write_project(tmp_path, with_gitignore=False)
    container = create_container()
    container.override_providers(
        project_locator_service=providers.Object(_FixedProjectLocatorService(project_root))
    )
    assert container.apply_service().run(config_root=config_root, display=display, planfile=None) == 0


def test_run_apply_prints_plan_and_not_legacy_sync_sections(
    tmp_path: Path, display: PlainDisplayService, capsys
) -> None:
    config_root, project_root = _write_project(tmp_path)
    container = create_container()
    container.override_providers(
        project_locator_service=providers.Object(_FixedProjectLocatorService(project_root))
    )
    assert container.apply_service().run(config_root=config_root, display=display, planfile=None) == 0

    out = capsys.readouterr().out
    assert "Planned Changes" in out
    assert "Syncing Agents" not in out
    assert "Syncing Skills" not in out


def test_run_apply_without_project_mentions_both_manifest_names(
    tmp_path: Path, display: PlainDisplayService, capsys
) -> None:
    config_root, _project_root = _write_project(tmp_path)
    container = create_container()
    container.override_providers(
        project_locator_service=providers.Object(_FixedProjectLocatorService(None))
    )
    assert container.apply_service().run(config_root=config_root, display=display, planfile=None) == 1

    out = capsys.readouterr().out
    assert "No .ai-sync.local.yaml or .ai-sync.yaml found. Create one first." in out


def test_run_doctor_without_project_mentions_both_manifest_names(
    tmp_path: Path, display: PlainDisplayService, capsys
) -> None:
    config_root, _project_root = _write_project(tmp_path)
    container = create_container()
    container.override_providers(
        project_locator_service=providers.Object(_FixedProjectLocatorService(None))
    )
    assert container.doctor_service().run(config_root=config_root, display=display) == 0

    out = capsys.readouterr().out
    assert "No project found (no .ai-sync.local.yaml or .ai-sync.yaml in current directory tree)" in out


def test_run_doctor_reports_local_manifest_name(
    tmp_path: Path, display: PlainDisplayService, capsys
) -> None:
    config_root, project_root = _write_project(tmp_path)
    (project_root / ".ai-sync.local.yaml").write_text("sources: {}\n", encoding="utf-8")
    container = create_container()
    container.override_providers(
        project_locator_service=providers.Object(_FixedProjectLocatorService(project_root))
    )
    assert container.doctor_service().run(config_root=config_root, display=display) == 0

    out = capsys.readouterr().out
    assert ".ai-sync.local.yaml: OK (0 sources declared)" in out


def test_run_uninstall_without_project_mentions_both_manifest_names(
    display: PlainDisplayService, capsys
) -> None:
    container = create_container()
    container.override_providers(
        project_locator_service=providers.Object(_FixedProjectLocatorService(None))
    )
    assert container.uninstall_service().run(display=display, apply=False) == 1

    out = capsys.readouterr().out
    assert "No .ai-sync.local.yaml or .ai-sync.yaml found. Nothing to uninstall." in out


def test_run_ui_starts_server_and_opens_browser(tmp_path: Path) -> None:
    config_root, project_root = _write_project(tmp_path)
    container = create_container()
    container.override_providers(
        project_locator_service=providers.Object(_FixedProjectLocatorService(project_root))
    )
    runtime = SimpleNamespace(container=container)
    browser_urls: list[str] = []
    server_calls: list[tuple[FastAPI, str, int]] = []

    def open_browser(url: str) -> bool:
        browser_urls.append(url)
        return True

    def run_server(app: FastAPI, *, host: str, port: int) -> None:
        server_calls.append((app, host, port))

    assert (
        cli._run_ui(
            runtime=runtime,
            config_root=config_root,
            host="0.0.0.0",
            port=9999,
            open_browser=open_browser,
            run_server=run_server,
        )
        == 0
    )
    assert browser_urls == ["http://127.0.0.1:9999"]
    assert len(server_calls) == 1
    app, host, port = server_calls[0]
    assert host == "0.0.0.0"
    assert port == 9999
    assert app.state.project_root == project_root


def test_run_ui_starts_server_without_project_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_root, _project_root = _write_project(tmp_path)
    container = create_container()
    container.override_providers(
        project_locator_service=providers.Object(_FixedProjectLocatorService(None))
    )
    runtime = SimpleNamespace(container=container)
    workspace_root = tmp_path / "scratch"
    workspace_root.mkdir()
    monkeypatch.chdir(workspace_root)
    browser_urls: list[str] = []
    server_calls: list[tuple[FastAPI, str, int]] = []

    def open_browser(url: str) -> bool:
        browser_urls.append(url)
        return True

    def run_server(app: FastAPI, *, host: str, port: int) -> None:
        server_calls.append((app, host, port))

    assert (
        cli._run_ui(
            runtime=runtime,
            config_root=config_root,
            host="127.0.0.1",
            port=8321,
            open_browser=open_browser,
            run_server=run_server,
        )
        == 0
    )
    assert browser_urls == ["http://127.0.0.1:8321"]
    assert len(server_calls) == 1
    app, host, port = server_calls[0]
    assert host == "127.0.0.1"
    assert port == 8321
    assert app.state.project_root is None
    assert app.state.workspace_root == workspace_root.resolve()


def _make_plan_with_deletion() -> ApplyPlan:
    return ApplyPlan(
        created_at="2024-01-01T00:00:00Z",
        project_root="/tmp",
        manifest_path="/tmp/.ai-sync.yaml",
        manifest_fingerprint="abc",
        actions=[
            PlanAction(
                action="delete",
                source_alias="company",
                kind="skill",
                resource="company/code-review",
                target="/tmp/skill",
                target_key="/tmp/skill",
            )
        ],
    )


def test_confirm_plan_deletions_accepts_yes(display: PlainDisplayService) -> None:
    plan = _make_plan_with_deletion()
    stdin = TTYStringIO()
    container = create_container(stdin=stdin, prompt_input=lambda _prompt: "y")
    assert container.apply_service().confirm_plan_deletions(plan, display) is True


def test_confirm_plan_deletions_rejects_no(display: PlainDisplayService) -> None:
    plan = _make_plan_with_deletion()
    stdin = TTYStringIO()
    container = create_container(stdin=stdin, prompt_input=lambda _prompt: "n")
    assert container.apply_service().confirm_plan_deletions(plan, display) is False


def test_confirm_plan_deletions_rejects_non_interactive(display: PlainDisplayService) -> None:
    plan = _make_plan_with_deletion()
    stdin = StringIO()
    container = create_container(stdin=stdin, prompt_input=lambda _prompt: "y")
    assert container.apply_service().confirm_plan_deletions(plan, display) is False
