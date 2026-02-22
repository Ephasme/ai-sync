import pytest

from ai_sync.precedence import apply_overrides, parse_override


def test_parse_override_string() -> None:
    assert parse_override("/servers/a/timeout=5000", parse_json=False) == ("/servers/a/timeout", "5000")


def test_parse_override_json() -> None:
    assert parse_override("/servers/a/enabled=true", parse_json=True) == ("/servers/a/enabled", True)


def test_parse_override_forbidden_secret_path() -> None:
    with pytest.raises(RuntimeError):
        parse_override("/servers/a/oauth/clientSecret=x", parse_json=False)


def test_apply_overrides_leaf_only() -> None:
    doc = {"servers": {"a": {"enabled": False, "timeout": 10}}}
    out = apply_overrides(doc, [("/servers/a/enabled", True), ("/servers/a/timeout", 20)])
    assert out["servers"]["a"]["enabled"] is True
    assert out["servers"]["a"]["timeout"] == 20


def test_apply_overrides_unknown_path_raises() -> None:
    with pytest.raises(RuntimeError):
        apply_overrides({"a": 1}, [("/b", 2)])
