from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_sync.adapters.state_store import IncompatibleStateError, StateStore
from ai_sync.helpers import ensure_dir
from ai_sync.data_classes.write_spec import WriteSpec
from ai_sync.di import create_container
from ai_sync.services.managed_output_service import ManagedOutputService


def _track_write(specs: list[WriteSpec], store: StateStore) -> None:
    container = create_container()
    container.managed_output_service().track_write_blocks(specs, store)


def test_track_write_text_marker_idempotent(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    target = tmp_path / ".cursor" / "rules" / "mcp-instructions.mdc"
    spec = WriteSpec(
        file_path=target,
        format="text",
        target="ai-sync:mcp-instructions",
        value="Hello world\n",
    )
    _track_write([spec], store)
    first = target.read_text(encoding="utf-8")
    assert "BEGIN ai-sync:mcp-instructions" in first

    _track_write([spec], store)
    second = target.read_text(encoding="utf-8")
    assert second == first


def test_track_write_structured_leaf_preserves_other_keys(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    target = tmp_path / ".cursor" / "cli-config.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('{"permissions":{"allow":["Read(*)"],"deny":["X"]},"other":1}', encoding="utf-8")

    spec = WriteSpec(
        file_path=target,
        format="json",
        target="/permissions/allow",
        value=["Read(*)", "Write(*)"],
    )
    _track_write([spec], store)
    content = target.read_text(encoding="utf-8")
    assert '"other": 1' in content
    assert "Write(*)" in content


def test_track_write_structured_root_list(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    target = tmp_path / "list.json"
    specs = [
        WriteSpec(file_path=target, format="json", target="/", value=[]),
        WriteSpec(file_path=target, format="json", target="/0", value={"name": "alpha"}),
    ]
    _track_write(specs, store)
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data == [{"name": "alpha"}]


def test_track_write_text_marker_with_literal_backslash_u(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    target = tmp_path / ".cursor" / "rules" / "mcp-instructions.mdc"
    spec = WriteSpec(
        file_path=target,
        format="text",
        target="ai-sync:mcp-instructions",
        value="Literal escape: \\u2019 should stay.\n",
    )
    _track_write([spec], store)
    _track_write([spec], store)
    content = target.read_text(encoding="utf-8")
    assert "\\u2019" in content


def test_track_write_agent_markdown_uses_full_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = StateStore(tmp_path)
    target = tmp_path / ".cursor" / "agents" / "test-agent.md"
    spec = WriteSpec(
        file_path=target,
        format="text",
        target="ai-sync:agent:test-agent",
        value="---\nname: test-agent\ndescription: Test agent\n---\n\nBody.\n",
    )
    _track_write([spec], store)
    content = target.read_text(encoding="utf-8")
    assert content.startswith("---\nname: test-agent")
    assert "BEGIN ai-sync:agent:test-agent" not in content


def test_state_version_2_in_persisted_state(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    store.load()
    store.save()
    raw = (tmp_path / ".ai-sync" / "state" / "state.json").read_text(encoding="utf-8")
    data = json.loads(raw)
    assert data["version"] == 2
    assert "effects" in data
    assert isinstance(data["effects"], list)


def test_incompatible_state_version_raises_error(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ai-sync" / "state"
    ensure_dir(state_dir)
    (state_dir / "state.json").write_text(
        json.dumps({"version": 1, "entries": []}),
        encoding="utf-8",
    )
    store = StateStore(tmp_path)
    store.load()
    with pytest.raises(IncompatibleStateError) as exc_info:
        store.check_version()
    assert "uninstall" in str(exc_info.value).lower()


def test_record_effect_persists_baseline(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    store.load()
    store.record_effect(
        effect_type="chmod",
        target="/foo/bar",
        target_key="chmod:/foo/bar",
        baseline={"prior_mode": 33188},
    )
    store.save()

    store2 = StateStore(tmp_path)
    store2.load()
    effects = store2.list_effects()
    assert len(effects) == 1
    assert effects[0] == {
        "effect_type": "chmod",
        "target": "/foo/bar",
        "target_key": "chmod:/foo/bar",
        "baseline": {"prior_mode": 33188},
    }
    assert store2.get_effect("chmod", "chmod:/foo/bar") is not None


def test_record_effect_idempotent(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    store.load()
    store.record_effect(
        effect_type="chmod",
        target="/foo/bar",
        target_key="chmod:/foo/bar",
        baseline={"prior_mode": 33188},
    )
    store.record_effect(
        effect_type="chmod",
        target="/foo/bar",
        target_key="chmod:/foo/bar",
        baseline={"prior_mode": 99999},
    )
    effects = store.list_effects()
    assert len(effects) == 1
    assert effects[0]["baseline"]["prior_mode"] == 33188


def test_cleanup_stale_entries_removes_state_when_file_still_desired(tmp_path: Path) -> None:
    """Stale state entries must be removed even when their file has other desired targets."""
    store = StateStore(tmp_path)
    store.load()

    shared_file = tmp_path / ".cursor" / "mcp.json"
    shared_file.parent.mkdir(parents=True, exist_ok=True)
    shared_file.write_text('{"mcpServers": {"kept": {}, "removed": {}}}', encoding="utf-8")

    store.ensure_entry(shared_file, "json", "/mcpServers/kept")
    store.ensure_entry(shared_file, "json", "/mcpServers/removed")
    store.save()

    desired_targets: set[tuple[str, str, str]] = {
        (str(shared_file), "json", "/mcpServers/kept"),
    }

    svc = ManagedOutputService()
    stale = svc._collect_stale_entries(store, desired_targets)
    assert len(stale) == 1
    assert stale[0]["target"] == "/mcpServers/removed"

    stale_specs = svc.build_stale_delete_specs(store, desired_targets)
    svc.cleanup_stale_entries(store, stale_specs, desired_targets)
    store.save()

    store2 = StateStore(tmp_path)
    store2.load()
    remaining = store2.list_entries()
    assert len(remaining) == 1
    assert remaining[0]["target"] == "/mcpServers/kept"

    assert shared_file.exists(), "File must not be deleted when it has other desired targets"


def test_managed_output_service_rejects_incompatible_state(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ai-sync" / "state"
    ensure_dir(state_dir)
    (state_dir / "state.json").write_text(
        json.dumps({"version": 1, "entries": []}),
        encoding="utf-8",
    )
    svc = ManagedOutputService()
    with pytest.raises(IncompatibleStateError):
        svc.classify_plan_key_specs(project_root=tmp_path, specs=[])
