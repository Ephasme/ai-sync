from __future__ import annotations

from pathlib import Path

import pytest

from ai_sync.artifacts import _load_artifact_yaml


def test_load_artifact_yaml_reads_sibling_prompt_file(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "prompts" / "engineer"
    bundle_dir.mkdir(parents=True)
    artifact_path = bundle_dir / "artifact.yaml"
    artifact_path.write_text(
        "slug: engineer\n"
        "description: Senior software engineer assistant\n",
        encoding="utf-8",
    )
    (bundle_dir / "prompt.md").write_text("## Task\nHelp\n", encoding="utf-8")

    meta, prompt = _load_artifact_yaml(
        artifact_path,
        defaults={"name": "engineer"},
        metadata_keys={"slug", "name", "description"},
        required_keys={"description"},
    )

    assert meta == {
        "name": "engineer",
        "slug": "engineer",
        "description": "Senior software engineer assistant",
    }
    assert prompt == "## Task\nHelp\n"


def test_load_artifact_yaml_rejects_inline_prompt_field(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "commands" / "session-summary"
    bundle_dir.mkdir(parents=True)
    artifact_path = bundle_dir / "artifact.yaml"
    artifact_path.write_text(
        "description: Session summary command\n"
        "prompt: |\n"
        "  Summarize the current session.\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="must not define an inline 'prompt' field"):
        _load_artifact_yaml(
            artifact_path,
            defaults={},
            metadata_keys={"description"},
            required_keys={"description"},
        )


def test_load_artifact_yaml_requires_prompt_file(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "rules" / "commit"
    bundle_dir.mkdir(parents=True)
    artifact_path = bundle_dir / "artifact.yaml"
    artifact_path.write_text(
        "description: Commit conventions\n"
        "alwaysApply: true\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="must include prompt.md"):
        _load_artifact_yaml(
            artifact_path,
            defaults={"alwaysApply": True},
            metadata_keys={"description", "alwaysApply", "globs"},
            required_keys={"description"},
        )
