"""Tests for helpers module."""
import tempfile
from pathlib import Path

import pytest

from helpers import (
    backup_context,
    copy_file_if_different,
    deep_merge,
    ensure_dir,
    extract_description,
    sync_tree_if_different,
    to_kebab_case,
    write_content_if_different,
)


class TestToKebabCase:
    def test_snake_case(self) -> None:
        assert to_kebab_case("my_agent_name") == "my-agent-name"

    def test_mixed_spaces_and_underscores(self) -> None:
        assert to_kebab_case("my agent_name") == "my-agent-name"

    def test_already_kebab(self) -> None:
        assert to_kebab_case("my-agent-name") == "my-agent-name"

    def test_uppercase(self) -> None:
        assert to_kebab_case("MyAgent") == "myagent"


class TestExtractDescription:
    def test_from_task_section(self) -> None:
        content = "## Task\n\nDo something useful with the codebase."
        assert extract_description(content) == "Do something useful with the codebase."

    def test_from_first_non_header_line(self) -> None:
        content = "# Title\n\nFirst actual line here."
        assert extract_description(content) == "First actual line here."

    def test_default_fallback(self) -> None:
        assert extract_description("# Only headers\n\n") == "AI Agent"

    def test_truncates_long_description(self) -> None:
        content = "## Task\n\n" + ("x" * 200)
        result = extract_description(content)
        assert len(result) == 153
        assert result.endswith("...")


class TestDeepMerge:
    def test_shallow_merge(self) -> None:
        base = {"a": 1, "b": 2}
        overlay = {"b": 3, "c": 4}
        result = deep_merge(base, overlay)
        assert result == {"a": 1, "b": 3, "c": 4}
        assert base["b"] == 2

    def test_nested_dict_merge(self) -> None:
        base = {"x": {"a": 1}}
        overlay = {"x": {"b": 2}}
        result = deep_merge(base, overlay)
        assert result == {"x": {"a": 1, "b": 2}}

    def test_overlay_replaces_list(self) -> None:
        base = {"items": [1, 2]}
        overlay = {"items": [3]}
        result = deep_merge(base, overlay)
        assert result == {"items": [3]}


class TestWriteContentIfDifferent:
    def test_creates_new_file(self, tmp_path: Path) -> None:
        p = tmp_path / "new.txt"
        assert write_content_if_different(p, "hello") is True
        assert p.read_text(encoding="utf-8") == "hello"

    def test_skips_when_identical(self, tmp_path: Path) -> None:
        p = tmp_path / "same.txt"
        p.write_text("identical", encoding="utf-8")
        assert write_content_if_different(p, "identical") is False
        assert p.read_text(encoding="utf-8") == "identical"

    def test_overwrites_when_different(self, tmp_path: Path) -> None:
        p = tmp_path / "diff.txt"
        p.write_text("old", encoding="utf-8")
        assert write_content_if_different(p, "new") is True
        assert p.read_text(encoding="utf-8") == "new"

    def test_skips_write_on_unreadable_file(self, tmp_path: Path) -> None:
        p = tmp_path / "binary.bin"
        p.write_bytes(b"\x80\x81\x82")
        assert write_content_if_different(p, "text") is False
        assert p.read_bytes() == b"\x80\x81\x82"


class TestCopyFileIfDifferent:
    def test_copies_when_missing(self, tmp_path: Path) -> None:
        src = tmp_path / "src.txt"
        dst = tmp_path / "dst.txt"
        src.write_text("content", encoding="utf-8")
        assert copy_file_if_different(src, dst) is True
        assert dst.read_text(encoding="utf-8") == "content"

    def test_skips_when_identical(self, tmp_path: Path) -> None:
        src = tmp_path / "src.txt"
        dst = tmp_path / "dst.txt"
        src.write_text("same", encoding="utf-8")
        dst.write_text("same", encoding="utf-8")
        assert copy_file_if_different(src, dst) is False


class TestEnsureDir:
    def test_creates_directory(self, tmp_path: Path) -> None:
        d = tmp_path / "nested" / "dir"
        ensure_dir(d)
        assert d.is_dir()

    def test_noop_when_exists(self, tmp_path: Path) -> None:
        ensure_dir(tmp_path)
        ensure_dir(tmp_path)


class TestSyncTreeIfDifferent:
    def test_copies_files(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.mkdir()
        (src / "a").write_text("a", encoding="utf-8")
        (src / "sub").mkdir(parents=True)
        (src / "sub" / "b").write_text("b", encoding="utf-8")
        skip = {"__pycache__"}
        changed = sync_tree_if_different(src, dst, skip)
        assert changed is True
        assert (dst / "a").read_text(encoding="utf-8") == "a"
        assert (dst / "sub" / "b").read_text(encoding="utf-8") == "b"

    def test_skips_patterns(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.mkdir()
        (src / "valid").write_text("ok", encoding="utf-8")
        (src / "__pycache__").mkdir()
        (src / "__pycache__" / "x").write_text("ignore", encoding="utf-8")
        changed = sync_tree_if_different(src, dst, {"__pycache__"})
        assert changed is True
        assert (dst / "valid").exists()
        assert not (dst / "__pycache__").exists()


class TestBackupContext:
    def test_context_manager_enters_and_exits(self) -> None:
        entered = False

        with backup_context(Path("/tmp/backup")):
            entered = True

        assert entered

    def test_nested_context_restores_outer(self) -> None:
        with backup_context(Path("/tmp/outer")):
            with backup_context(Path("/tmp/inner")):
                pass
            with backup_context(Path("/tmp/other")):
                pass
