from __future__ import annotations

from pathlib import Path

from dependency_injector import providers
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_sync.data_classes.resolved_source import ResolvedSource
from ai_sync.di import create_container
from ai_sync.web import create_app


class _StaticSourceResolverService:
    def __init__(self, resolved_sources: dict[str, ResolvedSource]) -> None:
        self._resolved_sources = resolved_sources

    def resolve_sources(self, project_root: Path, manifest) -> dict[str, ResolvedSource]:
        del project_root, manifest
        return self._resolved_sources


def _write_project(tmp_path: Path) -> tuple[Path, Path]:
    config_root = tmp_path / "config"
    config_root.mkdir()
    (config_root / "config.toml").write_text(
        'op_account_identifier = "x.1password.com"\n',
        encoding="utf-8",
    )

    source_root = tmp_path / "company-source"
    (source_root / "prompts" / "engineer").mkdir(parents=True)
    (source_root / "prompts" / "engineer" / "artifact.yaml").write_text(
        "slug: engineer\n"
        "name: Engineer\n"
        "description: Senior software engineer assistant\n",
        encoding="utf-8",
    )
    (source_root / "prompts" / "engineer" / "prompt.md").write_text("## Task\nHelp\n", encoding="utf-8")

    (source_root / "skills" / "code-review").mkdir(parents=True)
    (source_root / "skills" / "code-review" / "artifact.yaml").write_text(
        "name: code-review\n"
        "description: Review code skill\n",
        encoding="utf-8",
    )
    (source_root / "skills" / "code-review" / "prompt.md").write_text("# Skill\n", encoding="utf-8")

    (source_root / "commands" / "review" / "summary").mkdir(parents=True)
    (source_root / "commands" / "review" / "summary" / "artifact.yaml").write_text(
        "name: Review summary\n"
        "description: Review summary command\n",
        encoding="utf-8",
    )
    (source_root / "commands" / "review" / "summary" / "prompt.md").write_text(
        "Summarize review\n",
        encoding="utf-8",
    )

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
                "commands:",
                "  - company/review/summary",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return config_root, project_root


def _make_client(tmp_path: Path) -> tuple[TestClient, FastAPI]:
    config_root, project_root = _write_project(tmp_path)
    container = create_container()
    app = create_app(container=container, project_root=project_root, config_root=config_root)
    return TestClient(app), app


def _make_uninitialized_client(
    tmp_path: Path,
    *,
    source_resolver_service: _StaticSourceResolverService | None = None,
) -> tuple[TestClient, FastAPI]:
    config_root = tmp_path / "config"
    config_root.mkdir()
    (config_root / "config.toml").write_text(
        'op_account_identifier = "x.1password.com"\n',
        encoding="utf-8",
    )

    workspace_root = tmp_path / "scratch"
    workspace_root.mkdir()

    container = create_container()
    if source_resolver_service is not None:
        container.override_providers(
            source_resolver_service=providers.Object(source_resolver_service)
        )
    app = create_app(
        container=container,
        project_root=None,
        config_root=config_root,
        workspace_root=workspace_root,
    )
    return TestClient(app), app


def test_status_endpoint_returns_manifest_sources_and_selections(tmp_path: Path) -> None:
    client, _ = _make_client(tmp_path)

    response = client.get("/api/status")

    assert response.status_code == 200
    data = response.json()
    assert data["manifest"]["agents"] == ["company/engineer"]
    assert data["selections"]["commands"] == ["company/review/summary"]
    assert data["sources"][0]["alias"] == "company"
    assert data["sources"][0]["kind"] == "local"


def test_status_endpoint_returns_uninitialized_workspace_when_manifest_is_missing(tmp_path: Path) -> None:
    client, _ = _make_uninitialized_client(tmp_path)

    response = client.get("/api/status")

    assert response.status_code == 200
    data = response.json()
    assert data["initialized"] is False
    assert data["project_root"] is None
    assert data["manifest_path"] is None
    assert data["workspace_root"].endswith("/scratch")
    assert data["sources"] == []
    assert data["selections"]["agents"] == []


def test_manifest_endpoint_requires_initialized_workspace(tmp_path: Path) -> None:
    client, _ = _make_uninitialized_client(tmp_path)

    response = client.get("/api/manifest")

    assert response.status_code == 409
    assert "Create one first" in response.json()["detail"]


def test_bootstrap_manifest_endpoint_creates_default_manifest(tmp_path: Path) -> None:
    client, app = _make_uninitialized_client(
        tmp_path,
        source_resolver_service=_StaticSourceResolverService(
            {
                "sherpas-dev": ResolvedSource(
                    alias="sherpas-dev",
                    source="git@github.com:Les-Sherpas/ai-sync-config-dev.git",
                    version="v1.5.0",
                    root=tmp_path / "scratch" / ".ai-sync" / "sources" / "sherpas-dev",
                    kind="remote",
                    fingerprint="test-fingerprint",
                )
            }
        ),
    )

    response = client.post("/api/bootstrap-manifest")

    assert response.status_code == 200
    data = response.json()
    assert data["manifest_path"].endswith(".ai-sync.yaml")
    assert "sherpas-dev" in data["raw"]
    assert (
        data["manifest"]["sources"]["sherpas-dev"]["source"]
        == "git@github.com:Les-Sherpas/ai-sync-config-dev.git"
    )
    assert data["manifest"]["sources"]["sherpas-dev"]["version"] == "v1.5.0"
    assert app.state.project_root == app.state.workspace_root
    assert (app.state.workspace_root / ".ai-sync.yaml").exists()

    status_response = client.get("/api/status")
    assert status_response.status_code == 200
    assert status_response.json()["initialized"] is True
    assert status_response.json()["sources"][0]["alias"] == "sherpas-dev"


def test_source_catalog_endpoint_lists_available_entries(tmp_path: Path) -> None:
    client, _ = _make_client(tmp_path)

    response = client.get("/api/sources/company/catalog")

    assert response.status_code == 200
    entries = {entry["scoped_ref"]: entry for entry in response.json()["entries"]}
    assert set(entries) == {
        "company/engineer",
        "company/code-review",
        "company/review/summary",
        "company/commit",
        "company/context7",
    }
    assert entries["company/engineer"]["selected"] is True
    assert entries["company/review/summary"]["name"] == "Review summary"
    assert (
        entries["company/context7"]["description"]
        == "Library documentation lookup via Context7."
    )


def test_manifest_endpoint_returns_raw_and_parsed_manifest(tmp_path: Path) -> None:
    client, _ = _make_client(tmp_path)

    response = client.get("/api/manifest")

    assert response.status_code == 200
    data = response.json()
    assert data["manifest_path"].endswith(".ai-sync.yaml")
    assert "sources:" in data["raw"]
    assert data["manifest"]["commands"] == ["company/review/summary"]


def test_plan_endpoint_returns_plan_and_caches_context(tmp_path: Path) -> None:
    client, app = _make_client(tmp_path)

    response = client.get("/api/plan")

    assert response.status_code == 200
    data = response.json()
    assert "plan" in data
    assert isinstance(data["messages"], list)
    assert app.state.cached_plan_context is not None
    assert all("display_target" in action for action in data["plan"]["actions"])
    assert all("name" in action for action in data["plan"]["actions"])
    assert all("description" in action for action in data["plan"]["actions"])
    if data["plan"]["actions"]:
        assert not data["plan"]["actions"][0]["display_target"].startswith(str(app.state.project_root))


def test_plan_endpoint_returns_400_for_missing_local_env_used_by_mcp(tmp_path: Path) -> None:
    client, app = _make_client(tmp_path)
    project_root = app.state.project_root
    source_root = tmp_path / "company-source"

    (source_root / "mcp-servers" / "context7" / "artifact.yaml").write_text(
        "name: Context7\n"
        "description: Library documentation lookup via Context7.\n"
        "method: stdio\n"
        "command: npx\n"
        "dependencies:\n"
        "  env:\n"
        "    AWS_PROFILE:\n"
        "      local: {}\n"
        "      description: AWS profile name\n",
        encoding="utf-8",
    )
    manifest_path = project_root / ".ai-sync.yaml"
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8") + "mcp-servers:\n  - company/context7\n",
        encoding="utf-8",
    )

    response = client.get("/api/plan")

    assert response.status_code == 400
    assert "AWS_PROFILE" in response.json()["detail"]
    assert "local-scoped" in response.json()["detail"]
    assert app.state.cached_plan_context is None


def test_patch_manifest_updates_yaml_and_clears_cached_plan(tmp_path: Path) -> None:
    client, app = _make_client(tmp_path)
    client.get("/api/plan")

    response = client.patch(
        "/api/manifest",
        json={
            "changes": [
                {"section": "skills", "scoped_ref": "company/code-review", "enabled": True},
                {"section": "commands", "scoped_ref": "company/review/summary", "enabled": False},
            ]
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["manifest"]["skills"] == ["company/code-review"]
    assert data["manifest"].get("commands", []) == []
    assert "company/code-review" in data["raw"]
    assert "company/review/summary" not in data["raw"]
    assert app.state.cached_plan_context is None


def test_apply_endpoint_requires_cached_plan(tmp_path: Path) -> None:
    client, _ = _make_client(tmp_path)

    response = client.post("/api/apply")

    assert response.status_code == 400
    assert "GET /api/plan" in response.json()["detail"]


def test_apply_endpoint_rejects_stale_cached_plan(tmp_path: Path) -> None:
    client, app = _make_client(tmp_path)
    plan_response = client.get("/api/plan")
    assert plan_response.status_code == 200

    project_root = app.state.project_root
    manifest_path = project_root / ".ai-sync.yaml"
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8") + "skills:\n  - company/code-review\n",
        encoding="utf-8",
    )

    response = client.post("/api/apply")

    assert response.status_code == 409
    assert "stale" in response.json()["detail"]
    assert app.state.cached_plan_context is None


def test_apply_endpoint_runs_apply_from_cached_plan(tmp_path: Path) -> None:
    client, app = _make_client(tmp_path)
    plan_response = client.get("/api/plan")
    assert plan_response.status_code == 200

    response = client.post("/api/apply")

    assert response.status_code == 200
    assert response.json()["exit_code"] == 0
    assert app.state.cached_plan_context is None
    agent_prompt = app.state.project_root / ".codex" / "agents" / "company-engineer" / "prompt.md"
    assert agent_prompt.exists()
