from __future__ import annotations

from pathlib import Path

import pytest

from ai_sync.services.artifact_bundle_service import ArtifactBundleService

BUNDLE_SERVICE = ArtifactBundleService()


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

    bundle = BUNDLE_SERVICE.load_artifact_yaml(
        artifact_path,
        defaults={"name": "engineer"},
        metadata_keys={"slug", "name", "description"},
        required_keys={"description"},
    )

    assert bundle.metadata == {
        "name": "engineer",
        "slug": "engineer",
        "description": "Senior software engineer assistant",
    }
    assert bundle.prompt == "## Task\nHelp\n"


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
        BUNDLE_SERVICE.load_artifact_yaml(
            artifact_path,
            defaults={},
            metadata_keys={"description"},
            required_keys={"description"},
        )


def test_load_artifact_yaml_returns_none_when_prompt_file_is_missing(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "rules" / "commit"
    bundle_dir.mkdir(parents=True)
    artifact_path = bundle_dir / "artifact.yaml"
    artifact_path.write_text(
        "description: Commit conventions\n"
        "alwaysApply: true\n",
        encoding="utf-8",
    )

    bundle = BUNDLE_SERVICE.load_artifact_yaml(
        artifact_path,
        defaults={"alwaysApply": True},
        metadata_keys={"description", "alwaysApply", "globs"},
        required_keys={"description"},
    )

    assert bundle.metadata == {
        "alwaysApply": True,
        "description": "Commit conventions",
    }
    assert bundle.prompt is None


def test_require_prompt_raises_when_prompt_file_is_missing(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "rules" / "commit"
    bundle_dir.mkdir(parents=True)
    artifact_path = bundle_dir / "artifact.yaml"
    artifact_path.write_text(
        "description: Commit conventions\n"
        "alwaysApply: true\n",
        encoding="utf-8",
    )

    bundle = BUNDLE_SERVICE.load_artifact_yaml(
        artifact_path,
        defaults={"alwaysApply": True},
        metadata_keys={"description", "alwaysApply", "globs"},
        required_keys={"description"},
    )

    with pytest.raises(RuntimeError, match="must include prompt.md"):
        BUNDLE_SERVICE.require_prompt(bundle, artifact_path)


def test_load_artifact_yaml_raises_when_required_name_is_missing(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "commands" / "session-summary"
    bundle_dir.mkdir(parents=True)
    artifact_path = bundle_dir / "artifact.yaml"
    artifact_path.write_text(
        "description: Session summary command\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="must include: name"):
        BUNDLE_SERVICE.load_artifact_yaml(
            artifact_path,
            defaults={},
            metadata_keys={"name", "description"},
            required_keys={"name", "description"},
        )


def test_load_artifact_yaml_parses_env_dependencies_and_keeps_metadata_clean(
    tmp_path: Path,
) -> None:
    bundle_dir = tmp_path / "skills" / "slack-helper"
    bundle_dir.mkdir(parents=True)
    artifact_path = bundle_dir / "artifact.yaml"
    artifact_path.write_text(
        "name: slack-helper\n"
        "description: Post markdown to Slack\n"
        "disable-model-invocation: true\n"
        "dependencies:\n"
        "  env:\n"
        "    REGION: eu-west-3\n"
        "    SLACK_USER_TOKEN:\n"
        "      secret:\n"
        "        provider: op\n"
        "        ref: op://Vault/Item/token\n"
        "      description: Slack user token\n",
        encoding="utf-8",
    )
    (bundle_dir / "prompt.md").write_text("# Prompt\n", encoding="utf-8")

    bundle = BUNDLE_SERVICE.load_artifact_yaml(
        artifact_path,
        defaults={},
        metadata_keys=None,
        required_keys={"name", "description"},
    )

    assert "dependencies" not in bundle.metadata
    assert bundle.metadata["disable-model-invocation"] is True
    assert set(bundle.env_dependencies) == {"REGION", "SLACK_USER_TOKEN"}
    assert bundle.env_dependencies["REGION"].mode == "literal"
    assert bundle.env_dependencies["SLACK_USER_TOKEN"].mode == "secret"


def test_load_artifact_yaml_rejects_invalid_dependency_shape(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "skills" / "slack-helper"
    bundle_dir.mkdir(parents=True)
    artifact_path = bundle_dir / "artifact.yaml"
    artifact_path.write_text(
        "name: slack-helper\n"
        "description: Post markdown to Slack\n"
        "dependencies:\n"
        "  env:\n"
        "    SLACK_USER_TOKEN:\n"
        "      secret:\n"
        "        provider: op\n",
        encoding="utf-8",
    )
    (bundle_dir / "prompt.md").write_text("# Prompt\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="secret.ref"):
        BUNDLE_SERVICE.load_artifact_yaml(
            artifact_path,
            defaults={},
            metadata_keys=None,
            required_keys={"name", "description"},
        )
