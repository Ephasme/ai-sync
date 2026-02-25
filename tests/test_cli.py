from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from ai_sync import cli
from ai_sync.display import PlainDisplay


@pytest.fixture()
def display() -> PlainDisplay:
    return PlainDisplay()


@pytest.fixture()
def log_path(tmp_path: Path) -> Path:
    return tmp_path / "ai-sync.errors.log"


def test_run_install_writes_config(monkeypatch, tmp_path: Path, display: PlainDisplay, log_path: Path) -> None:
    monkeypatch.setattr(cli, "ensure_layout", lambda: tmp_path)
    args = argparse.Namespace(op_account="Test", force=True)
    assert cli._run_install(args, display, log_path) == 0
    config_path = tmp_path / "config.toml"
    assert config_path.exists()
    assert "op_account" in config_path.read_text(encoding="utf-8")


def test_run_install_requires_op_account(monkeypatch, tmp_path: Path, display: PlainDisplay, log_path: Path) -> None:
    monkeypatch.setattr(cli, "ensure_layout", lambda: tmp_path)
    monkeypatch.delenv("OP_ACCOUNT", raising=False)
    monkeypatch.delenv("OP_SERVICE_ACCOUNT_TOKEN", raising=False)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    args = argparse.Namespace(op_account=None, force=True)
    assert cli._run_install(args, display, log_path) == 1


def test_run_import_copies_repo(monkeypatch, tmp_path: Path, display: PlainDisplay, log_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "prompts").mkdir(parents=True)
    (repo / "prompts" / "agent.md").write_text("hi", encoding="utf-8")
    (repo / "skills" / "skill-one").mkdir(parents=True)
    (repo / "skills" / "skill-one" / "SKILL.md").write_text("# Skill\n", encoding="utf-8")
    (repo / "mcp-servers.yaml").write_text("servers:\n  ok:\n    method: stdio\n    command: npx\n", encoding="utf-8")
    (repo / "defaults.yaml").write_text("agents: []\n", encoding="utf-8")
    (repo / ".env.tpl").write_text("X=1\n", encoding="utf-8")
    monkeypatch.setattr(cli, "ensure_layout", lambda: tmp_path / "dest")
    args = argparse.Namespace(repo=str(repo))
    assert cli._run_import(args, display, log_path) == 0
    assert (tmp_path / "dest" / "config" / "prompts" / "agent.md").exists()
    assert (tmp_path / "dest" / "config" / "skills" / "skill-one" / "SKILL.md").exists()
    assert (tmp_path / "dest" / "config" / "mcp-servers.yaml").exists()
    assert (tmp_path / "dest" / "config" / "defaults.yaml").exists()
    assert (tmp_path / "dest" / ".env.tpl").exists()


def test_run_doctor_missing_config(monkeypatch, tmp_path: Path, display: PlainDisplay) -> None:
    monkeypatch.setattr(cli, "get_config_root", lambda: tmp_path)
    assert cli._run_doctor(tmp_path, display) == 1


def test_run_doctor_ok(monkeypatch, tmp_path: Path, display: PlainDisplay) -> None:
    monkeypatch.setattr(cli, "get_config_root", lambda: tmp_path)
    (tmp_path / "config.toml").write_text("op_account = \"X\"\n", encoding="utf-8")
    (tmp_path / "config").mkdir()
    for sub in ["prompts", "skills"]:
        (tmp_path / "config" / sub).mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "mcp-servers.yaml").write_text("servers: {}\n", encoding="utf-8")
    monkeypatch.setenv("OP_ACCOUNT", "X")
    assert cli._run_doctor(tmp_path, display) == 0


def test_resolve_repo_source_local(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    with cli._resolve_repo_source(str(repo)) as resolved:
        assert resolved == repo


def test_run_apply_success(monkeypatch, tmp_path: Path, display: PlainDisplay, log_path: Path) -> None:
    config_root = tmp_path / "root"
    config_root.mkdir()
    (config_root / "config.toml").write_text("op_account = \"x\"\n", encoding="utf-8")
    (config_root / "config").mkdir(parents=True)
    (config_root / "config" / "prompts").mkdir(parents=True)
    (config_root / "config" / "mcp-servers.yaml").write_text("servers: {}\n", encoding="utf-8")
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / ".ai-sync.yaml").write_text("agents: []\nskills: []\n", encoding="utf-8")

    monkeypatch.setattr(cli, "find_project_root", lambda: project_root)
    monkeypatch.setattr(cli, "run_apply", lambda **kwargs: 0)
    args = argparse.Namespace(plain=True)
    assert cli._run_apply(args, config_root, display, log_path) == 0


def test_build_parser_has_install_apply_init() -> None:
    parser = cli._build_parser()
    for cmd in ("install", "apply", "init", "import", "doctor", "uninstall"):
        result = parser.parse_args([cmd] if cmd != "import" else [cmd, "--repo", "/tmp"])
        assert result.command == cmd
