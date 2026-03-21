import pytest

from ai_sync.services.mcp_preparation_service import McpPreparationService
from ai_sync.services.one_password_cli_service import OnePasswordCliService

SERVICE = McpPreparationService()


def test_interpolate_env_refs_supports_both_forms() -> None:
    env = {"A": "1", "B": "2"}
    assert SERVICE.resolve_env_refs("$A-${B}", env) == "1-2"


def test_interpolate_env_refs_missing_raises() -> None:
    with pytest.raises(RuntimeError):
        SERVICE.resolve_env_refs("$MISSING", {})


def test_resolve_env_refs_nested() -> None:
    data = {"x": ["$A", {"y": "${B}"}]}
    assert SERVICE.resolve_env_refs(data, {"A": "foo", "B": "bar"}) == {
        "x": ["foo", {"y": "bar"}]
    }


def test_parse_injected_env() -> None:
    content = "A=1\n# c\nB=2\n"
    assert OnePasswordCliService.parse_injected_env(content) == {"A": "1", "B": "2"}


def test_parse_injected_env_rejects_invalid() -> None:
    with pytest.raises(RuntimeError):
        OnePasswordCliService.parse_injected_env("export A=1\n")


def test_collect_env_refs_nested() -> None:
    data = {
        "servers": {
            "a": {"env": {"KEY": "${API_KEY}"}},
            "b": {"args": ["--token", "$TOKEN"]},
            "c": {"static": "no-refs-here"},
        }
    }
    assert SERVICE.collect_env_refs(data) == {"API_KEY", "TOKEN"}


def test_collect_env_refs_empty_on_no_refs() -> None:
    assert SERVICE.collect_env_refs({"x": 1, "y": [True, "plain"]}) == set()


def test_interpolate_double_dollar_escapes_to_literal() -> None:
    env = {"FOO": "resolved"}
    assert SERVICE.resolve_env_refs("$$FOO", env) == "$FOO"
    assert SERVICE.resolve_env_refs("$${FOO}", env) == "${FOO}"


def test_interpolate_mixed_escaped_and_resolved() -> None:
    env = {"A": "1", "B": "2"}
    assert SERVICE.resolve_env_refs("$$A-$B", env) == "$A-2"


def test_collect_env_refs_ignores_escaped() -> None:
    data = {"args": ["--flag=$$NOT_A_REF", "--key=$REAL_REF"]}
    assert SERVICE.collect_env_refs(data) == {"REAL_REF"}


def test_resolve_env_refs_nested_with_escape() -> None:
    data = {"args": ["cmd --id=$$MY_VAR"], "env": {"MY_VAR": "${MY_VAR}"}}
    resolved = SERVICE.resolve_env_refs(data, {"MY_VAR": "secret"})
    assert resolved == {"args": ["cmd --id=$MY_VAR"], "env": {"MY_VAR": "secret"}}
