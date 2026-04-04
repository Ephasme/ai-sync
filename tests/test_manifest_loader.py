from __future__ import annotations

from pathlib import Path

import pytest

from ai_sync.models.env_dependency import EnvDependency
from ai_sync.data_classes.resolved_source import ResolvedSource
from ai_sync.services.mcp_preparation_service import McpPreparationService


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


def _source(alias: str, root: Path) -> ResolvedSource:
    return ResolvedSource(alias=alias, source=str(root), version=None, root=root, kind="local", fingerprint="abc")


def test_load_manifest_missing_returns_empty(tmp_path: Path) -> None:
    display = FakeDisplay()
    assert McpPreparationService().load_manifest(tmp_path, display) == {}


def test_load_manifest_invalid_yaml_raises(tmp_path: Path) -> None:
    display = FakeDisplay()
    server_dir = tmp_path / "mcp_servers" / "bad"
    server_dir.mkdir(parents=True)
    (server_dir / "artifact.yaml").write_text("servers: [", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Failed to load"):
        McpPreparationService().load_manifest(tmp_path, display)


def test_load_manifest_validation_error_raises(tmp_path: Path) -> None:
    display = FakeDisplay()
    server_dir = tmp_path / "mcp_servers" / "bad"
    server_dir.mkdir(parents=True)
    (server_dir / "artifact.yaml").write_text("123\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="expected a mapping"):
        McpPreparationService().load_manifest(tmp_path, display)


def test_load_manifest_valid(tmp_path: Path) -> None:
    display = FakeDisplay()
    server_dir = tmp_path / "mcp_servers" / "ok"
    server_dir.mkdir(parents=True)
    (server_dir / "artifact.yaml").write_text(
        "name: OK\n"
        "description: OK MCP server.\n"
        "method: stdio\n"
        "command: npx\n",
        encoding="utf-8",
    )
    data = McpPreparationService().load_manifest(tmp_path, display)
    assert "servers" in data
    assert "ok" in data["servers"]


def test_load_and_filter_mcp_by_scoped_refs(tmp_path: Path) -> None:
    display = FakeDisplay()
    company = tmp_path / "company"
    (company / "mcp_servers" / "srv-a").mkdir(parents=True)
    (company / "mcp_servers" / "srv-a" / "artifact.yaml").write_text(
        "name: Server A\n"
        "description: Server A MCP.\n"
        "method: stdio\n"
        "command: npx\n",
        encoding="utf-8",
    )
    (company / "mcp_servers" / "srv-b").mkdir(parents=True)
    (company / "mcp_servers" / "srv-b" / "artifact.yaml").write_text(
        "name: Server B\n"
        "description: Server B MCP.\n"
        "method: stdio\n"
        "command: npx\n",
        encoding="utf-8",
    )
    result = McpPreparationService().load_and_filter_mcp(
        {"company": _source("company", company)},
        ["company/srv-a"],
        display,
    )
    assert "srv-a" in result
    assert "srv-b" not in result


def test_load_and_filter_mcp_rejects_missing_server(tmp_path: Path) -> None:
    display = FakeDisplay()
    company = tmp_path / "company"
    (company / "mcp_servers" / "srv-a").mkdir(parents=True)
    (company / "mcp_servers" / "srv-a" / "artifact.yaml").write_text(
        "name: Server A\n"
        "description: Server A MCP.\n"
        "method: stdio\n"
        "command: npx\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="was not found"):
        McpPreparationService().load_and_filter_mcp({"company": _source("company", company)}, ["company/srv-b"], display)


def test_load_and_filter_mcp_rejects_colliding_output_ids(tmp_path: Path) -> None:
    display = FakeDisplay()
    company = tmp_path / "company"
    (company / "mcp_servers" / "fetch").mkdir(parents=True)
    (company / "mcp_servers" / "fetch" / "artifact.yaml").write_text(
        "name: Fetch Company\n"
        "description: Company MCP fetch server.\n"
        "method: stdio\n"
        "command: company\n",
        encoding="utf-8",
    )
    frontend = tmp_path / "frontend"
    (frontend / "mcp_servers" / "fetch").mkdir(parents=True)
    (frontend / "mcp_servers" / "fetch" / "artifact.yaml").write_text(
        "name: Fetch Frontend\n"
        "description: Frontend MCP fetch server.\n"
        "method: stdio\n"
        "command: frontend\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="collision"):
        McpPreparationService().load_and_filter_mcp(
            {
                "company": _source("company", company),
                "frontend": _source("frontend", frontend),
            },
            ["company/fetch", "frontend/fetch"],
            display,
        )


def test_load_manifest_warns_on_missing_artifact_yaml(tmp_path: Path) -> None:
    display = FakeDisplay()
    (tmp_path / "mcp_servers" / "bad").mkdir(parents=True)
    assert McpPreparationService().load_manifest(tmp_path, display) == {"servers": {}}
    assert any("without artifact.yaml" in msg for _, msg in display.messages)


def test_load_manifest_parses_server_dependencies(tmp_path: Path) -> None:
    display = FakeDisplay()
    server_dir = tmp_path / "mcp_servers" / "ok"
    server_dir.mkdir(parents=True)
    (server_dir / "artifact.yaml").write_text(
        "name: OK\n"
        "description: OK MCP server.\n"
        "method: stdio\n"
        "command: npx\n"
        "dependencies:\n"
        "  env:\n"
        "    API_KEY:\n"
        "      secret:\n"
        "        provider: op\n"
        "        ref: op://Vault/Item/api_key\n",
        encoding="utf-8",
    )
    data = McpPreparationService().load_manifest(tmp_path, display)
    deps = data["servers"]["ok"]["dependencies"]
    assert "API_KEY" in deps
    assert isinstance(deps["API_KEY"], EnvDependency)
    assert deps["API_KEY"].mode == "secret"


def test_load_manifest_accepts_authored_server_env(tmp_path: Path) -> None:
    display = FakeDisplay()
    server_dir = tmp_path / "mcp_servers" / "ok"
    server_dir.mkdir(parents=True)
    (server_dir / "artifact.yaml").write_text(
        "name: OK\n"
        "description: OK MCP server.\n"
        "method: stdio\n"
        "command: npx\n"
        "env:\n"
        "  API_KEY: ${RAW_API_KEY}\n",
        encoding="utf-8",
    )
    data = McpPreparationService().load_manifest(tmp_path, display)
    assert data["servers"]["ok"]["env"] == {"API_KEY": "${RAW_API_KEY}"}


def test_load_manifest_rejects_authored_client_override_env(tmp_path: Path) -> None:
    display = FakeDisplay()
    server_dir = tmp_path / "mcp_servers" / "bad"
    server_dir.mkdir(parents=True)
    (server_dir / "artifact.yaml").write_text(
        "name: bad\n"
        "description: bad MCP server.\n"
        "method: stdio\n"
        "command: npx\n"
        "client_overrides:\n"
        "  codex:\n"
        "    env:\n"
        "      API_KEY: value\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="env"):
        McpPreparationService().load_manifest(tmp_path, display)


def test_load_manifest_rejects_invalid_server_dependency_shape(tmp_path: Path) -> None:
    display = FakeDisplay()
    server_dir = tmp_path / "mcp_servers" / "bad"
    server_dir.mkdir(parents=True)
    (server_dir / "artifact.yaml").write_text(
        "name: bad\n"
        "description: bad MCP server.\n"
        "method: stdio\n"
        "command: npx\n"
        "dependencies:\n"
        "  env:\n"
        "    API_KEY:\n"
        "      secret:\n"
        "        provider: op\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="secret.ref"):
        McpPreparationService().load_manifest(tmp_path, display)


def test_synthesize_env_from_dependencies_uses_inject_as() -> None:
    svc = McpPreparationService()
    source = {
        "stripe": {
            "dependencies": {
                "STRIPE_LIVE_SECRET_KEY": EnvDependency(
                    name="STRIPE_LIVE_SECRET_KEY",
                    mode="secret",
                    secret_provider="op",
                    secret_ref="op://Vault/Item/live",
                    inject_as="STRIPE_SECRET_KEY",
                )
            }
        }
    }
    runtime = {"stripe": {"command": "npx", "args": []}}
    out = svc.synthesize_env_from_dependencies(
        runtime,
        source,
        {"STRIPE_LIVE_SECRET_KEY": "sk_live_xxx"},
    )
    stripe_server = out["stripe"]
    assert isinstance(stripe_server, dict)
    assert stripe_server["env"] == {"STRIPE_SECRET_KEY": "sk_live_xxx"}
