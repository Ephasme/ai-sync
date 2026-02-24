from __future__ import annotations

import pytest

from ai_sync.path_ops import (
    delete_at_path,
    escape_path_segment,
    get_at_path,
    set_at_path,
    split_path,
)


# ---------------------------------------------------------------------------
# split_path
# ---------------------------------------------------------------------------


class TestSplitPath:
    def test_root_returns_empty(self) -> None:
        assert split_path("/") == []

    def test_empty_string_returns_empty(self) -> None:
        assert split_path("") == []

    def test_single_segment(self) -> None:
        assert split_path("/foo") == ["foo"]

    def test_multiple_segments(self) -> None:
        assert split_path("/a/b/c") == ["a", "b", "c"]

    def test_numeric_segment(self) -> None:
        assert split_path("/items/0") == ["items", "0"]

    def test_tilde_escaping(self) -> None:
        assert split_path("/a~1b") == ["a/b"]
        assert split_path("/a~0b") == ["a~b"]

    def test_invalid_path_no_leading_slash(self) -> None:
        with pytest.raises(ValueError, match="Invalid path"):
            split_path("foo/bar")


# ---------------------------------------------------------------------------
# escape_path_segment
# ---------------------------------------------------------------------------


class TestEscapePathSegment:
    def test_plain_string(self) -> None:
        assert escape_path_segment("foo") == "foo"

    def test_slash_escaped(self) -> None:
        assert escape_path_segment("a/b") == "a~1b"

    def test_tilde_escaped(self) -> None:
        assert escape_path_segment("a~b") == "a~0b"

    def test_both_escaped(self) -> None:
        assert escape_path_segment("~/path") == "~0~1path"


# ---------------------------------------------------------------------------
# get_at_path
# ---------------------------------------------------------------------------


class TestGetAtPath:
    def test_root(self) -> None:
        data = {"a": 1}
        assert get_at_path(data, "/") is data

    def test_dict_leaf(self) -> None:
        assert get_at_path({"a": {"b": 42}}, "/a/b") == 42

    def test_list_index(self) -> None:
        assert get_at_path({"items": [10, 20, 30]}, "/items/1") == 20

    def test_nested_list(self) -> None:
        assert get_at_path([[1, 2], [3, 4]], "/1/0") == 3

    def test_missing_dict_key_raises(self) -> None:
        with pytest.raises(KeyError):
            get_at_path({"a": 1}, "/b")

    def test_missing_list_index_raises(self) -> None:
        with pytest.raises(KeyError):
            get_at_path({"items": [1]}, "/items/5")

    def test_scalar_intermediate_raises(self) -> None:
        with pytest.raises(KeyError):
            get_at_path({"a": "string"}, "/a/b")


# ---------------------------------------------------------------------------
# set_at_path
# ---------------------------------------------------------------------------


class TestSetAtPath:
    def test_root_replacement(self) -> None:
        result = set_at_path({}, "/", [1, 2, 3])
        assert result == [1, 2, 3]

    def test_dict_leaf(self) -> None:
        data = {"a": {"b": 1}}
        set_at_path(data, "/a/b", 99)
        assert data["a"]["b"] == 99

    def test_creates_intermediate_dicts(self) -> None:
        data: dict = {}
        set_at_path(data, "/a/b", "val")
        assert data == {"a": {"b": "val"}}

    def test_list_index_set(self) -> None:
        data: list = [{"name": "old"}]
        set_at_path(data, "/0/name", "new")
        assert data[0]["name"] == "new"

    def test_list_index_extends(self) -> None:
        data: list = []
        set_at_path(data, "/2", "val")
        assert data == [None, None, "val"]

    def test_ambiguous_numeric_raises(self) -> None:
        data: dict = {}
        with pytest.raises(ValueError, match="Ambiguous path"):
            set_at_path(data, "/items/0", "x")

    def test_explicit_list_then_index_ok(self) -> None:
        data: dict = {"items": []}
        set_at_path(data, "/items/0", "x")
        assert data == {"items": ["x"]}

    def test_nested_dict_in_list(self) -> None:
        data: list = [{}]
        set_at_path(data, "/0/key", "val")
        assert data == [{"key": "val"}]


# ---------------------------------------------------------------------------
# delete_at_path
# ---------------------------------------------------------------------------


class TestDeleteAtPath:
    def test_root_returns_empty_dict(self) -> None:
        assert delete_at_path({"a": 1}, "/") == {}

    def test_dict_key_removed(self) -> None:
        data = {"a": 1, "b": 2}
        delete_at_path(data, "/a")
        assert data == {"b": 2}

    def test_dict_missing_key_is_noop(self) -> None:
        data = {"a": 1}
        delete_at_path(data, "/nonexistent")
        assert data == {"a": 1}

    def test_list_element_nulled(self) -> None:
        data = {"items": ["a", "b", "c"]}
        delete_at_path(data, "/items/1")
        assert data == {"items": ["a", None, "c"]}

    def test_list_out_of_range_is_noop(self) -> None:
        data: list = [1, 2]
        delete_at_path(data, "/5")
        assert data == [1, 2]

    def test_nested_dict_key(self) -> None:
        data = {"a": {"b": 1, "c": 2}}
        delete_at_path(data, "/a/b")
        assert data == {"a": {"c": 2}}

    def test_ambiguous_numeric_raises(self) -> None:
        data: dict = {}
        with pytest.raises(ValueError, match="Ambiguous path"):
            delete_at_path(data, "/items/0")
