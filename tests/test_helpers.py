from pathlib import Path

from ai_sync.helpers import (
    copy_file_if_different,
    deep_merge,
    ensure_dir,
    extract_description,
    sync_tree_if_different,
    to_kebab_case,
    write_content_if_different,
)


def test_to_kebab_case() -> None:
    assert to_kebab_case("my_agent_name") == "my-agent-name"
    assert to_kebab_case("my agent_name") == "my-agent-name"


def test_extract_description() -> None:
    assert extract_description("## Task\n\nDo thing.") == "Do thing."
    assert extract_description("# Title\n\nBody line") == "Body line"


def test_deep_merge() -> None:
    assert deep_merge({"x": {"a": 1}}, {"x": {"b": 2}}) == {"x": {"a": 1, "b": 2}}


def test_write_content_if_different(tmp_path: Path) -> None:
    p = tmp_path / "a.txt"
    assert write_content_if_different(p, "x") is True
    assert write_content_if_different(p, "x") is False


def test_copy_file_if_different(tmp_path: Path) -> None:
    src = tmp_path / "s"
    dst = tmp_path / "d"
    src.write_text("abc", encoding="utf-8")
    assert copy_file_if_different(src, dst)


def test_ensure_dir(tmp_path: Path) -> None:
    d = tmp_path / "a" / "b"
    ensure_dir(d)
    assert d.exists()


def test_sync_tree_if_different(tmp_path: Path) -> None:
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    (src / "x").write_text("1", encoding="utf-8")
    assert sync_tree_if_different(src, dst, {"__pycache__"})
