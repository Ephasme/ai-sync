"""Service for collecting rule artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from ai_sync.data_classes.artifact import Artifact
from ai_sync.data_classes.write_spec import WriteSpec
from ai_sync.helpers import string_metadata_value
from ai_sync.models import split_scoped_ref
from ai_sync.services.artifact_bundle_service import ArtifactBundleService

if TYPE_CHECKING:
    from ai_sync.clients.base import Client
    from ai_sync.data_classes.resolved_source import ResolvedSource
    from ai_sync.data_classes.runtime_env import RuntimeEnv
    from ai_sync.models import ProjectManifest
def _render_claude_rule(raw_content: str, meta: dict) -> str:
    description = str(meta.get("description", "Project rule"))
    always_apply = bool(meta.get("alwaysApply", True))
    lines = [
        "---",
        f"description: {json.dumps(description)}",
        f"alwaysApply: {'true' if always_apply else 'false'}",
    ]
    globs = meta.get("globs")
    if isinstance(globs, list) and globs:
        lines.append(f"globs: {json.dumps([str(item) for item in globs])}")
    lines.append("---")
    body = raw_content.lstrip()
    return "\n".join(lines) + "\n\n" + body


class RuleArtifactService:
    """Build `Artifact` entries for selected global and client rule outputs."""

    def __init__(self, *, artifact_bundle_service: ArtifactBundleService) -> None:
        self._artifact_bundle_service = artifact_bundle_service

    def collect_artifacts(
        self,
        *,
        project_root: Path,
        manifest: "ProjectManifest",
        resolved_sources: dict[str, "ResolvedSource"],
        runtime_env: "RuntimeEnv",
        mcp_manifest: dict,
        clients: list["Client"],
    ) -> list[Artifact]:
        del runtime_env, mcp_manifest

        artifacts: list[Artifact] = []
        rules_dir = project_root / ".ai-sync" / "rules"

        for rule_ref in manifest.rules:
            alias, rule_name = split_scoped_ref(rule_ref)
            rule_path = self._artifact_bundle_service.bundle_entry_path(
                resolved_sources[alias].root / "rules",
                Path(rule_name),
            )
            if not rule_path.exists():
                raise RuntimeError(f"Selected rule {rule_ref!r} was not found.")
            bundle = self._artifact_bundle_service.load_artifact_yaml(
                rule_path,
                defaults={"alwaysApply": True},
                metadata_keys={"name", "description", "alwaysApply", "globs"},
                required_keys={"name", "description"},
            )
            artifact_name = string_metadata_value(
                bundle.metadata.get("name"),
                Path(rule_name).name,
            )
            artifact_description = string_metadata_value(
                bundle.metadata.get("description"),
                "",
            )

            prefixed_name = f"{alias}-{rule_name}"
            target = rules_dir / f"{prefixed_name}.md"
            marker_id = f"ai-sync:rule:{prefixed_name}"

            def make_global_resolve(
                p: Path = rule_path,
                t: Path = target,
                mid: str = marker_id,
            ):
                def resolve():
                    bundle = self._artifact_bundle_service.load_artifact_yaml(
                        p,
                        defaults={"alwaysApply": True},
                        metadata_keys={"description", "alwaysApply", "globs"},
                        required_keys={"description"},
                    )
                    content = self._artifact_bundle_service.require_prompt(bundle, p)
                    return [WriteSpec(file_path=t, format="text", target=mid, value=content)]

                return resolve

            artifacts.append(
                Artifact(
                    kind="rule",
                    resource=rule_ref,
                    name=artifact_name,
                    description=artifact_description,
                    source_alias=alias,
                    plan_key=str(target),
                    secret_backed=False,
                    client="global",
                    resolve_fn=make_global_resolve(),
                )
            )

            client_marker_id = f"ai-sync:rule:{prefixed_name}:client"
            for client in clients:
                if client.name != "claude":
                    continue
                client_target = client.config_dir / "rules" / f"{prefixed_name}.md"

                def make_client_resolve(
                    p: Path = rule_path,
                    t: Path = client_target,
                    mid: str = client_marker_id,
                ):
                    def resolve():
                        bundle = self._artifact_bundle_service.load_artifact_yaml(
                            p,
                            defaults={"alwaysApply": True},
                            metadata_keys={"description", "alwaysApply", "globs"},
                            required_keys={"description"},
                        )
                        content = self._artifact_bundle_service.require_prompt(bundle, p)
                        rendered = _render_claude_rule(content, bundle.metadata)
                        return [WriteSpec(file_path=t, format="text", target=mid, value=rendered)]

                    return resolve

                artifacts.append(
                    Artifact(
                        kind="rule",
                        resource=rule_ref,
                        name=artifact_name,
                        description=artifact_description,
                        source_alias=alias,
                        plan_key=str(client_target),
                        secret_backed=False,
                        client=client.name,
                        resolve_fn=make_client_resolve(),
                    )
                )

        return artifacts
