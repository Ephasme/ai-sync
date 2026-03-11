from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ai_sync import op_inject


def test_extract_and_inject_refs() -> None:
    lines = ["A=1", "B=op://vault/item/field", "# C=op://skip", "D=op://vault/item/other"]
    refs, mapping = op_inject._extract_op_refs(lines)
    assert refs == ["op://vault/item/field", "op://vault/item/other"]
    injected = op_inject._inject_resolved(lines, mapping, {"op://vault/item/field": "X"})
    assert "B=X" in injected
    assert "D=op://vault/item/other" in injected


def test_resolve_auth_prefers_token(monkeypatch) -> None:
    monkeypatch.setenv("OP_SERVICE_ACCOUNT_TOKEN", "token")
    monkeypatch.delenv("OP_ACCOUNT", raising=False)
    assert op_inject._resolve_auth(None) == "token"


def test_resolve_auth_uses_account(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OP_SERVICE_ACCOUNT_TOKEN", raising=False)
    monkeypatch.setenv("OP_ACCOUNT", "acc")
    auth = op_inject._resolve_auth(tmp_path)
    assert isinstance(auth, op_inject.DesktopAuth)
    assert auth.account_name == "acc"


def test_load_runtime_env_missing_file(tmp_path: Path) -> None:
    assert op_inject.load_runtime_env_from_op(tmp_path / "missing.env") == {}


@dataclass
class DummySecret:
    secret: str


@dataclass
class DummyResponse:
    content: DummySecret | None = None
    error: Exception | None = None


@dataclass
class DummyResolveAll:
    individual_responses: dict[str, DummyResponse]


@dataclass
class DummySecrets:
    async def resolve_all(self, refs: list[str]) -> DummyResolveAll:
        return DummyResolveAll({ref: DummyResponse(content=DummySecret(secret="ok")) for ref in refs})


@dataclass
class DummyClient:
    secrets: DummySecrets


async def _fake_authenticate(*_args, **_kwargs) -> DummyClient:
    return DummyClient(secrets=DummySecrets())


def test_load_runtime_env_async_resolves(monkeypatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env.ai-sync.tpl"
    env_file.write_text("TOKEN=op://vault/item/field\n", encoding="utf-8")
    monkeypatch.setattr(op_inject.Client, "authenticate", _fake_authenticate)
    monkeypatch.setenv("OP_SERVICE_ACCOUNT_TOKEN", "token")
    env = asyncio.run(op_inject._load_runtime_env_async(env_file, tmp_path))
    assert env["TOKEN"] == "ok"


def test_load_runtime_env_from_op_prefers_cli_inject(monkeypatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env.ai-sync.tpl"
    env_file.write_text("TOKEN=op://Example Vault/example/token\n", encoding="utf-8")

    async def _unexpected_authenticate(*_args, **_kwargs):
        raise AssertionError("SDK fallback should not run when CLI inject succeeds")

    def _fake_run(args, **kwargs):
        if args[:3] == ["op", "inject", "--in-file"]:
            assert kwargs["env"]["OP_ACCOUNT"] == "example.1password.com"
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="TOKEN=resolved-by-cli\n",
                stderr="",
            )
        raise AssertionError(args)

    monkeypatch.setattr(op_inject.subprocess, "run", _fake_run)
    monkeypatch.setenv("OP_ACCOUNT", "example.1password.com")
    monkeypatch.setattr(op_inject.Client, "authenticate", _unexpected_authenticate)

    env = op_inject.load_runtime_env_from_op(env_file, tmp_path)
    assert env["TOKEN"] == "resolved-by-cli"


def test_load_runtime_env_from_op_falls_back_to_sdk_when_cli_missing(monkeypatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env.ai-sync.tpl"
    env_file.write_text("TOKEN=op://vault/item/field\n", encoding="utf-8")

    def _missing_op(*_args, **_kwargs):
        raise FileNotFoundError("op")

    monkeypatch.setattr(op_inject.subprocess, "run", _missing_op)
    monkeypatch.setattr(op_inject.Client, "authenticate", _fake_authenticate)
    monkeypatch.setenv("OP_SERVICE_ACCOUNT_TOKEN", "token")

    env = op_inject.load_runtime_env_from_op(env_file, tmp_path)
    assert env["TOKEN"] == "ok"
