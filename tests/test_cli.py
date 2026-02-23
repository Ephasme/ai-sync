from __future__ import annotations

import argparse
import os
from pathlib import Path

import pytest

from ai_sync import cli


def test_run_setup_writes_config(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "ensure_layout", lambda: tmp_path)
    args = argparse.Namespace(op_account="Test", force=True)
    assert cli._run_setup(args) == 0
    config_path = tmp_path / "config.toml"
    assert config_path.exists()
    assert "op_account" in config_path.read_text(encoding="utf-8")


def test_run_setup_requires_op_account(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "ensure_layout", lambda: tmp_path)
    monkeypatch.delenv("OP_ACCOUNT", raising=False)
    monkeypatch.delenv("OP_SERVICE_ACCOUNT_TOKEN", raising=False)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    args = argparse.Namespace(op_account=None, force=True)
    assert cli._run_setup(args) == 1


def test_run_import_copies_repo(monkeypatch, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "prompts").mkdir(parents=True)
    (repo / "prompts" / "agent.md").write_text("hi", encoding="utf-8")
    (repo / "skills" / "skill-one").mkdir(parents=True)
    (repo / "skills" / "skill-one" / "SKILL.md").write_text("# Skill\n", encoding="utf-8")
    (repo / "mcp-servers.yaml").write_text("servers:\n  ok:\n    method: stdio\n    command: npx\n", encoding="utf-8")
    (repo / "client-settings.yaml").write_text("mode: normal\n", encoding="utf-8")
    (repo / ".env.tpl").write_text("X=1\n", encoding="utf-8")
    monkeypatch.setattr(cli, "ensure_layout", lambda: tmp_path / "dest")
    args = argparse.Namespace(repo=str(repo))
    assert cli._run_import(args) == 0
    assert (tmp_path / "dest" / "config" / "prompts" / "agent.md").exists()
    assert (tmp_path / "dest" / "config" / "skills" / "skill-one" / "SKILL.md").exists()
    assert (tmp_path / "dest" / "config" / "mcp-servers" / "servers.yaml").exists()
    assert (tmp_path / "dest" / "config" / "client-settings" / "settings.yaml").exists()
    assert (tmp_path / "dest" / ".env.tpl").exists()


def test_run_doctor_missing_config(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "get_config_root", lambda: tmp_path)
    assert cli._run_doctor() == 1


def test_run_doctor_ok(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "get_config_root", lambda: tmp_path)
    (tmp_path / "config.toml").write_text("op_account = \"X\"\n", encoding="utf-8")
    (tmp_path / "config").mkdir()
    for sub in ["prompts", "skills", "mcp-servers", "client-settings"]:
        (tmp_path / "config" / sub).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OP_ACCOUNT", "X")
    assert cli._run_doctor() == 0


def test_run_sync_invalid_override(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "get_config_root", lambda: tmp_path)
    args = argparse.Namespace(
        force=False,
        no_interactive=True,
        plain=True,
        override=["bad"],
        override_json=[],
    )
    assert cli._run_sync(args) == 1


def test_resolve_repo_source_local(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    with cli._resolve_repo_source(str(repo)) as resolved:
        assert resolved == repo


def test_run_sync_success(monkeypatch, tmp_path: Path) -> None:
    config_root = tmp_path / "root"
    config_root.mkdir()
    (config_root / "config.toml").write_text("op_account = \"x\"\n", encoding="utf-8")
    monkeypatch.setattr(cli, "get_config_root", lambda: config_root)
    monkeypatch.setattr(cli, "run_sync", lambda **_kwargs: 0)
    args = argparse.Namespace(
        force=False,
        no_interactive=True,
        plain=True,
        override=[],
        override_json=[],
    )
    assert cli._run_sync(args) == 0
