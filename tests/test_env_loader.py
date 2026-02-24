import pytest

from ai_sync.env_loader import collect_env_refs, interpolate_env_refs, resolve_env_refs_in_obj
from ai_sync.op_inject import parse_injected_env


def test_interpolate_env_refs_supports_both_forms() -> None:
    env = {"A": "1", "B": "2"}
    assert interpolate_env_refs("$A-${B}", env) == "1-2"


def test_interpolate_env_refs_missing_raises() -> None:
    with pytest.raises(RuntimeError):
        interpolate_env_refs("$MISSING", {})


def test_resolve_env_refs_nested() -> None:
    data = {"x": ["$A", {"y": "${B}"}]}
    assert resolve_env_refs_in_obj(data, {"A": "foo", "B": "bar"}) == {"x": ["foo", {"y": "bar"}]}


def test_parse_injected_env() -> None:
    content = "A=1\n# c\nB=2\n"
    assert parse_injected_env(content) == {"A": "1", "B": "2"}


def test_parse_injected_env_rejects_invalid() -> None:
    with pytest.raises(RuntimeError):
        parse_injected_env("export A=1\n")


def test_collect_env_refs_nested() -> None:
    data = {
        "servers": {
            "a": {"env": {"KEY": "${API_KEY}"}},
            "b": {"args": ["--token", "$TOKEN"]},
            "c": {"static": "no-refs-here"},
        }
    }
    assert collect_env_refs(data) == {"API_KEY", "TOKEN"}


def test_collect_env_refs_empty_on_no_refs() -> None:
    assert collect_env_refs({"x": 1, "y": [True, "plain"]}) == set()


def test_interpolate_double_dollar_escapes_to_literal() -> None:
    env = {"FOO": "resolved"}
    assert interpolate_env_refs("$$FOO", env) == "$FOO"
    assert interpolate_env_refs("$${FOO}", env) == "${FOO}"


def test_interpolate_mixed_escaped_and_resolved() -> None:
    env = {"A": "1", "B": "2"}
    assert interpolate_env_refs("$$A-$B", env) == "$A-2"


def test_collect_env_refs_ignores_escaped() -> None:
    data = {"args": ["--flag=$$NOT_A_REF", "--key=$REAL_REF"]}
    assert collect_env_refs(data) == {"REAL_REF"}


def test_resolve_env_refs_nested_with_escape() -> None:
    data = {"args": ['cmd --id=$$MY_VAR'], "env": {"MY_VAR": "${MY_VAR}"}}
    resolved = resolve_env_refs_in_obj(data, {"MY_VAR": "secret"})
    assert resolved == {"args": ["cmd --id=$MY_VAR"], "env": {"MY_VAR": "secret"}}
