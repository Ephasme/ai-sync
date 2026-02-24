from pathlib import Path

from ai_sync.helpers import (
    ensure_dir,
    extract_description,
    to_kebab_case,
)


def test_to_kebab_case() -> None:
    assert to_kebab_case("my_agent_name") == "my-agent-name"
    assert to_kebab_case("my agent_name") == "my-agent-name"


def test_extract_description() -> None:
    assert extract_description("## Task\n\nDo thing.") == "Do thing."
    assert extract_description("# Title\n\nBody line") == "Body line"


def test_ensure_dir(tmp_path: Path) -> None:
    d = tmp_path / "a" / "b"
    ensure_dir(d)
    assert d.exists()
