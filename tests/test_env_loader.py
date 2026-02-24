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
