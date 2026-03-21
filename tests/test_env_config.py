from __future__ import annotations

from pathlib import Path

import pytest

from ai_sync.models import parse_artifact_dependencies
from ai_sync.services.environment_service import EnvironmentService


class _FakeSecretService:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def resolve(
        self,
        values: dict[str, str],
        config_root: Path | None = None,
    ) -> dict[str, str]:
        del config_root
        self.calls.append(dict(values))
        return {name: f"resolved:{ref}" for name, ref in values.items()}


def _service(fake: _FakeSecretService | None = None) -> EnvironmentService:
    return EnvironmentService(op_secret_service=fake or _FakeSecretService())  # type: ignore[arg-type]


def test_parse_dependencies_literal_local_and_secret_modes() -> None:
    deps = parse_artifact_dependencies(
        {
            "env": {
                "AWS_REGION": "eu-west-3",
                "AWS_PROFILE": {
                    "local": {"default": "sandbox-admin"},
                    "description": "Local profile",
                },
                "SLACK_USER_TOKEN": {
                    "secret": {
                        "provider": "op",
                        "ref": "op://Vault/Item/SLACK_USER_TOKEN",
                    }
                },
            }
        },
        context="test",
    ).env
    assert deps["AWS_REGION"].mode == "literal"
    assert deps["AWS_REGION"].literal == "eu-west-3"
    assert deps["AWS_PROFILE"].mode == "local"
    assert deps["AWS_PROFILE"].local_default == "sandbox-admin"
    assert deps["SLACK_USER_TOKEN"].mode == "secret"
    assert deps["SLACK_USER_TOKEN"].secret_provider == "op"


def test_parse_dependencies_rejects_invalid_provider() -> None:
    with pytest.raises(RuntimeError, match="provider must be 'op'"):
        parse_artifact_dependencies(
            {
                "env": {
                    "TOKEN": {
                        "secret": {"provider": "vault", "ref": "vault://token"},
                    }
                }
            },
            context="test",
        )


def test_parse_dependencies_rejects_invalid_var_name() -> None:
    with pytest.raises(RuntimeError, match="invalid env var name"):
        parse_artifact_dependencies({"env": {"bad-name": "x"}}, context="test")


def test_parse_dependencies_rejects_local_secret_mode_conflict() -> None:
    with pytest.raises(RuntimeError, match="exactly one of 'local' or 'secret'"):
        parse_artifact_dependencies(
            {
                "env": {
                    "TOKEN": {
                        "local": {},
                        "secret": {"provider": "op", "ref": "op://Vault/Item/TOKEN"},
                    }
                }
            },
            context="test",
        )


def test_read_existing_env_file_with_values(tmp_path: Path) -> None:
    (tmp_path / ".env.ai-sync").write_text("A=1\nB=hello\n", encoding="utf-8")
    result = _service().read_existing_env_file(tmp_path)
    assert result == {"A": "1", "B": "hello"}


def test_read_existing_env_file_missing(tmp_path: Path) -> None:
    assert _service().read_existing_env_file(tmp_path) == {}


def test_read_existing_env_file_empty(tmp_path: Path) -> None:
    (tmp_path / ".env.ai-sync").write_text("", encoding="utf-8")
    assert _service().read_existing_env_file(tmp_path) == {}


def test_resolve_runtime_env_uses_local_value_then_default_then_warns(tmp_path: Path) -> None:
    fake = _FakeSecretService()
    service = _service(fake)
    (tmp_path / ".env.ai-sync").write_text("HAS_LOCAL=from-file\n", encoding="utf-8")
    deps = parse_artifact_dependencies(
        {
            "env": {
                "HAS_LOCAL": {"local": {}},
                "WITH_DEFAULT": {"local": {"default": "fallback"}},
                "MISSING_LOCAL": {"local": {}, "description": "missing token"},
                "LITERAL_VAL": "fixed",
                "SECRET_VAL": {
                    "secret": {"provider": "op", "ref": "op://Vault/Item/secret"}
                },
            }
        },
        context="test",
    ).env

    resolved = service.resolve_runtime_env(tmp_path, deps, None)
    assert resolved.env["HAS_LOCAL"] == "from-file"
    assert resolved.env["WITH_DEFAULT"] == "fallback"
    assert resolved.env["LITERAL_VAL"] == "fixed"
    assert resolved.env["SECRET_VAL"] == "resolved:op://Vault/Item/secret"
    assert "MISSING_LOCAL" in resolved.unfilled_local_vars
    assert any("MISSING_LOCAL" in warning for warning in resolved.warnings)
    assert fake.calls == [{"SECRET_VAL": "op://Vault/Item/secret"}]


def test_resolve_runtime_env_does_not_call_secret_service_without_secret_dependencies(
    tmp_path: Path,
) -> None:
    fake = _FakeSecretService()
    service = _service(fake)
    deps = parse_artifact_dependencies({"env": {"LITERAL_ONLY": "x"}}, context="test").env
    resolved = service.resolve_runtime_env(tmp_path, deps, None)
    assert resolved.env["LITERAL_ONLY"] == "x"
    assert fake.calls == []


def test_parse_dependencies_rejects_unknown_top_level_key() -> None:
    with pytest.raises(RuntimeError, match="supports only 'env' and 'binaries'"):
        parse_artifact_dependencies({"env": {}, "extra": {}}, context="test")
