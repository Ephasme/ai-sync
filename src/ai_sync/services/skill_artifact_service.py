"""Service for collecting skill artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import tomli
import yaml

from ai_sync.data_classes.artifact import Artifact
from ai_sync.data_classes.write_spec import WriteSpec
from ai_sync.helpers import escape_path_segment, string_metadata_value, to_kebab_case
from ai_sync.models import split_scoped_ref
from ai_sync.services.artifact_bundle_service import ArtifactBundleService

if TYPE_CHECKING:
    from ai_sync.clients.base import Client
    from ai_sync.data_classes.prepared_artifacts import PreparedArtifacts
    from ai_sync.data_classes.resolved_source import ResolvedSource
    from ai_sync.data_classes.runtime_env import RuntimeEnv
    from ai_sync.models import ProjectManifest

SKIP_PATTERNS = {".venv", "node_modules", "__pycache__", ".git", ".DS_Store"}


def _render_skill_markdown(meta: dict, prompt: str) -> str:
    frontmatter = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
    body = prompt if prompt.endswith("\n") else f"{prompt}\n"
    return f"---\n{frontmatter}\n---\n\n{body}"


def _parse_structured_content(content: str, fmt: str) -> dict | list:
    if not content.strip():
        return {}
    if fmt == "json":
        return json.loads(content)
    if fmt == "toml":
        return tomli.loads(content)
    if fmt == "yaml":
        data = yaml.safe_load(content)
        return data if isinstance(data, (dict, list)) else {}
    raise ValueError(f"Unsupported format: {fmt}")


def _flatten_structured_to_specs(file_path: Path, fmt: str, data: object) -> list[WriteSpec]:
    specs: list[WriteSpec] = []

    def walk(node: object, prefix: str) -> None:
        if isinstance(node, dict):
            if not node:
                specs.append(
                    WriteSpec(file_path=file_path, format=fmt, target=prefix or "/", value={})
                )
                return
            for key, value in node.items():
                next_prefix = f"{prefix}/{escape_path_segment(str(key))}"
                walk(value, next_prefix)
            return
        if isinstance(node, list):
            specs.append(
                WriteSpec(file_path=file_path, format=fmt, target=prefix or "/", value=[])
            )
            if not node:
                return
            for idx, value in enumerate(node):
                next_prefix = f"{prefix}/{idx}"
                walk(value, next_prefix)
            return
        specs.append(WriteSpec(file_path=file_path, format=fmt, target=prefix or "/", value=node))

    walk(data, "")
    return specs


class SkillArtifactService:
    """Build `Artifact` entries for selected skill bundles."""

    def __init__(self, *, artifact_bundle_service: ArtifactBundleService) -> None:
        self._artifact_bundle_service = artifact_bundle_service

    def collect_artifacts(
        self,
        *,
        project_root: Path,
        manifest: "ProjectManifest",
        resolved_sources: dict[str, "ResolvedSource"],
        runtime_env: "RuntimeEnv",
        prepared_artifacts: "PreparedArtifacts",
        clients: list["Client"],
    ) -> list[Artifact]:
        del project_root, runtime_env, prepared_artifacts

        artifacts: list[Artifact] = []
        for skill_ref in manifest.skills:
            alias, skill_name = split_scoped_ref(skill_ref)
            skill_dir = resolved_sources[alias].root / "skills" / skill_name
            artifact_path = skill_dir / "artifact.yaml"
            if not (skill_dir.is_dir() and artifact_path.exists()):
                raise RuntimeError(f"Selected skill {skill_ref!r} was not found.")
            kebab_name = to_kebab_case(Path(skill_name).name)
            prefixed_name = f"{alias}-{kebab_name}"
            bundle = self._artifact_bundle_service.load_artifact_yaml(
                artifact_path,
                defaults={},
                metadata_keys=None,
                required_keys={"name", "description"},
            )
            artifact_name = string_metadata_value(bundle.metadata.get("name"), kebab_name)
            artifact_description = string_metadata_value(
                bundle.metadata.get("description"),
                "",
            )

            for client in clients:
                target_skill_dir = client.get_skills_dir() / prefixed_name

                def make_resolve(
                    ap: Path = artifact_path,
                    sd: Path = skill_dir,
                    kn: str = kebab_name,
                    tsd: Path = target_skill_dir,
                ):
                    def resolve():
                        return self._build_skill_specs(ap, sd, kn, tsd)

                    return resolve

                artifacts.append(
                    Artifact(
                        kind="skill",
                        resource=skill_ref,
                        name=artifact_name,
                        description=artifact_description,
                        source_alias=alias,
                        plan_key=str(target_skill_dir),
                        secret_backed=any(
                            dep.mode == "secret"
                            for dep in bundle.env_dependencies.values()
                        ),
                        client=client.name,
                        resolve_fn=make_resolve(),
                        env_dependencies=bundle.env_dependencies,
                    )
                )
        return artifacts

    def _build_skill_specs(
        self,
        artifact_path: Path,
        skill_dir: Path,
        kebab_name: str,
        target_skill_dir: Path,
    ) -> list[WriteSpec]:
        specs: list[WriteSpec] = []
        bundle = self._artifact_bundle_service.load_artifact_yaml(
            artifact_path,
            defaults={},
            metadata_keys=None,
            required_keys={"name", "description"},
        )
        prompt = self._artifact_bundle_service.require_prompt(bundle, artifact_path)
        specs.append(
            WriteSpec(
                file_path=target_skill_dir / "SKILL.md",
                format="text",
                target=f"ai-sync:skill:{kebab_name}:SKILL.md",
                value=_render_skill_markdown(bundle.metadata, prompt),
            )
        )

        files_dir = skill_dir / "files"
        if not files_dir.is_dir():
            return specs

        for sub in files_dir.rglob("*"):
            rel = sub.relative_to(files_dir)
            if any(part in SKIP_PATTERNS for part in rel.parts) or sub.is_dir():
                continue
            target = target_skill_dir / rel
            if sub.name.endswith(".json"):
                fmt = "json"
            elif sub.name.endswith(".toml"):
                fmt = "toml"
            elif sub.name.endswith((".yaml", ".yml")):
                fmt = "yaml"
            else:
                fmt = "text"
            content = sub.read_text(encoding="utf-8")
            marker_id = f"ai-sync:skill:{kebab_name}:{rel.as_posix()}"
            if fmt == "text":
                specs.append(
                    WriteSpec(file_path=target, format=fmt, target=marker_id, value=content)
                )
                continue
            data = _parse_structured_content(content, fmt)
            specs.extend(_flatten_structured_to_specs(target, fmt, data))
        return specs
