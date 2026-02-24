from __future__ import annotations

import json
from pathlib import Path

from ai_sync.track_write import WriteSpec, track_write_blocks


def test_track_write_text_marker_idempotent(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / ".cursor" / "rules" / "mcp-instructions.mdc"
    spec = WriteSpec(
        file_path=target,
        format="text",
        target="ai-sync:mcp-instructions",
        value="Hello world\n",
    )
    track_write_blocks([spec])
    first = target.read_text(encoding="utf-8")
    assert "BEGIN ai-sync:mcp-instructions" in first

    track_write_blocks([spec])
    second = target.read_text(encoding="utf-8")
    assert second == first


def test_track_write_structured_leaf_preserves_other_keys(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / ".cursor" / "cli-config.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('{"permissions":{"allow":["Read(*)"],"deny":["X"]},"other":1}', encoding="utf-8")

    spec = WriteSpec(
        file_path=target,
        format="json",
        target="/permissions/allow",
        value=["Read(*)", "Write(*)"],
    )
    track_write_blocks([spec])
    content = target.read_text(encoding="utf-8")
    assert '"other": 1' in content
    assert "Write(*)" in content


def test_track_write_structured_root_list(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / "list.json"
    specs = [
        WriteSpec(file_path=target, format="json", target="/", value=[]),
        WriteSpec(file_path=target, format="json", target="/0", value={"name": "alpha"}),
    ]
    track_write_blocks(specs)
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data == [{"name": "alpha"}]


def test_track_write_text_marker_with_literal_backslash_u(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / ".cursor" / "rules" / "mcp-instructions.mdc"
    spec = WriteSpec(
        file_path=target,
        format="text",
        target="ai-sync:mcp-instructions",
        value="Literal escape: \\u2019 should stay.\n",
    )
    track_write_blocks([spec])
    track_write_blocks([spec])
    content = target.read_text(encoding="utf-8")
    assert "\\u2019" in content


def test_track_write_agent_markdown_uses_full_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / ".cursor" / "agents" / "test-agent.md"
    spec = WriteSpec(
        file_path=target,
        format="text",
        target="ai-sync:agent:test-agent",
        value="---\nname: test-agent\ndescription: Test agent\n---\n\nBody.\n",
    )
    track_write_blocks([spec])
    content = target.read_text(encoding="utf-8")
    assert content.startswith("---\nname: test-agent")
    assert "BEGIN ai-sync:agent:test-agent" not in content
