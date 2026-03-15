"""Service for loading artifact bundle metadata and prompt content."""

from __future__ import annotations

from pathlib import Path

import yaml

from ai_sync.data_classes.artifact_bundle import ArtifactBundle

BUNDLE_ARTIFACT_FILENAME = "artifact.yaml"
BUNDLE_PROMPT_FILENAME = "prompt.md"


class ArtifactBundleService:
    """Resolve bundle paths and load bundle metadata from source directories."""

    def bundle_entry_path(self, base_dir: Path, artifact_rel: Path) -> Path:
        return base_dir / artifact_rel / BUNDLE_ARTIFACT_FILENAME

    def bundle_prompt_path(self, artifact_path: Path) -> Path:
        return artifact_path.with_name(BUNDLE_PROMPT_FILENAME)

    def load_artifact_yaml(
        self,
        artifact_path: Path,
        *,
        defaults: dict[str, object],
        metadata_keys: set[str] | None,
        required_keys: set[str],
    ) -> ArtifactBundle:
        result = dict(defaults)
        try:
            data = yaml.safe_load(artifact_path.read_text(encoding="utf-8")) or {}
        except (yaml.YAMLError, OSError) as exc:
            raise RuntimeError(
                f"Failed to load artifact file {artifact_path.name}: {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise RuntimeError(
                f"Artifact file {artifact_path.name} must contain a YAML mapping."
            )
        if "prompt" in data:
            raise RuntimeError(
                f"Artifact file {artifact_path.name} must not define an inline 'prompt' field. "
                f"Move the markdown body to {BUNDLE_PROMPT_FILENAME}."
            )
        if metadata_keys is None:
            for key, value in data.items():
                if value is not None:
                    result[key] = value
        else:
            for key in metadata_keys:
                if key in data and data[key] is not None:
                    result[key] = data[key]
        missing_keys = sorted(key for key in required_keys if key not in result)
        if missing_keys:
            raise RuntimeError(
                f"Artifact file {artifact_path.name} must include: {', '.join(missing_keys)}"
            )
        prompt_path = self.bundle_prompt_path(artifact_path)
        prompt: str | None = None
        if prompt_path.is_file():
            try:
                prompt = prompt_path.read_text(encoding="utf-8")
            except OSError as exc:
                raise RuntimeError(
                    f"Failed to load prompt file {prompt_path.name}: {exc}"
                ) from exc
        return ArtifactBundle(metadata=result, prompt=prompt)

    def require_prompt(self, bundle: ArtifactBundle, artifact_path: Path) -> str:
        if bundle.prompt is None:
            raise RuntimeError(
                f"Artifact bundle {artifact_path.parent} must include {BUNDLE_PROMPT_FILENAME}."
            )
        return bundle.prompt
