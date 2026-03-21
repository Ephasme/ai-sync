"""Universal artifact preparation service."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ai_sync.data_classes.prepared_artifacts import PreparedArtifacts
from ai_sync.data_classes.prepared_mcp_server import PreparedMcpServer
from ai_sync.models import split_scoped_ref
from ai_sync.models.env_dependency import EnvDependency
from ai_sync.services.artifact_bundle_service import ArtifactBundleService
from ai_sync.services.display_service import DisplayService
from ai_sync.services.environment_service import EnvironmentService
from ai_sync.services.mcp_preparation_service import McpPreparationService

if TYPE_CHECKING:
    from ai_sync.data_classes.resolved_source import ResolvedSource
    from ai_sync.data_classes.runtime_env import RuntimeEnv
    from ai_sync.models import ProjectManifest


class ArtifactPreparationService:
    """Single orchestration entry for universal artifact preparation.

    Handles the pre-runtime and post-runtime preparation phases for all
    artifact kinds, producing a shared ``PreparedArtifacts`` context that
    downstream collectors, requirement checks, and plan builders consume.
    """

    def __init__(
        self,
        *,
        mcp_preparation_service: McpPreparationService,
        artifact_bundle_service: ArtifactBundleService,
        environment_service: EnvironmentService,
    ) -> None:
        self._mcp_preparation_service = mcp_preparation_service
        self._artifact_bundle_service = artifact_bundle_service
        self._environment_service = environment_service

    def prepare(
        self,
        *,
        project_root: Path,
        manifest: "ProjectManifest",
        resolved_sources: dict[str, "ResolvedSource"],
        config_root: Path | None,
        display: DisplayService,
    ) -> tuple[PreparedArtifacts, "RuntimeEnv"]:
        """Run the full preparation pipeline and return prepared context + RuntimeEnv."""

        # --- PRE-RUNTIME PHASE ---
        # 1. Validate and select MCP servers, preserving scoped provenance
        mcp_source_configs = self._mcp_preparation_service.load_and_filter_mcp(
            resolved_sources, manifest.mcp_servers, display
        )

        # 2. Merge selected env dependencies into the global dependency set
        selected_dependencies = self._collect_env_dependencies(
            manifest=manifest,
            resolved_sources=resolved_sources,
            mcp_source_configs=mcp_source_configs,
        )

        # --- RUNTIME ENV RESOLUTION ---
        # 3. Resolve RuntimeEnv
        runtime_env = self._environment_service.resolve_runtime_env(
            project_root,
            selected_dependencies,
            config_root,
        )
        for warning in runtime_env.warnings:
            display.print(f"Warning: {warning}", style="warning")

        # --- POST-RUNTIME PHASE ---
        # 4-8. Finalize MCP servers with runtime env
        prepared_mcp = self._finalize_mcp_servers(
            mcp_source_configs=mcp_source_configs,
            runtime_env=runtime_env,
            selected_dependencies=selected_dependencies,
            mcp_server_refs=manifest.mcp_servers,
        )

        prepared = PreparedArtifacts(
            mcp_servers=prepared_mcp,
            has_local_env=bool(runtime_env.local_vars),
        )
        return prepared, runtime_env

    def _collect_env_dependencies(
        self,
        *,
        manifest: "ProjectManifest",
        resolved_sources: dict[str, "ResolvedSource"],
        mcp_source_configs: dict,
    ) -> dict[str, EnvDependency]:
        """Merge env dependencies from all selected artifacts."""
        merged: dict[str, EnvDependency] = {}

        def merge_from(ref: str, dependencies: dict[str, EnvDependency]) -> None:
            for name, dep in dependencies.items():
                existing = merged.get(name)
                if existing is None:
                    merged[name] = dep
                    continue
                if existing.semantic_key() != dep.semantic_key():
                    raise RuntimeError(
                        f"Conflicting env dependency declarations for {name!r}: "
                        f"{ref} conflicts with a previously selected declaration."
                    )
                if not existing.description and dep.description:
                    merged[name] = EnvDependency(
                        name=existing.name,
                        mode=existing.mode,
                        description=dep.description,
                        literal=existing.literal,
                        local_default=existing.local_default,
                        secret_provider=existing.secret_provider,
                        secret_ref=existing.secret_ref,
                    )

        def collect_bundle(ref: str, base_dir_name: str) -> None:
            alias, resource_id = split_scoped_ref(ref)
            artifact_path = (
                resolved_sources[alias].root / base_dir_name / resource_id / "artifact.yaml"
            )
            if not artifact_path.is_file():
                raise RuntimeError(f"Selected resource {ref!r} was not found.")
            bundle = self._artifact_bundle_service.load_artifact_yaml(
                artifact_path,
                defaults={},
                metadata_keys=None,
                required_keys={"name", "description"},
            )
            merge_from(ref, bundle.env_dependencies)

        for ref in manifest.agents:
            collect_bundle(ref, "prompts")
        for ref in manifest.skills:
            collect_bundle(ref, "skills")
        for ref in manifest.commands:
            collect_bundle(ref, "commands")
        for ref in manifest.rules:
            collect_bundle(ref, "rules")

        for ref in manifest.mcp_servers:
            _, server_id = split_scoped_ref(ref)
            server = mcp_source_configs.get(server_id)
            if not isinstance(server, dict):
                continue
            deps = server.get("dependencies") or {}
            if not isinstance(deps, dict):
                continue
            typed_deps = {
                name: dep for name, dep in deps.items() if isinstance(dep, EnvDependency)
            }
            merge_from(ref, typed_deps)

        return merged

    def _finalize_mcp_servers(
        self,
        *,
        mcp_source_configs: dict,
        runtime_env: "RuntimeEnv",
        selected_dependencies: dict[str, EnvDependency],
        mcp_server_refs: list[str],
    ) -> list[PreparedMcpServer]:
        """Post-runtime MCP finalization following the 8-step env-processing order.

        1. validate and select (already done in pre-runtime)
        2. merge env dependencies (already done in _collect_env_dependencies)
        3. resolve RuntimeEnv (already done by caller)
        4. collect required MCP env references from runtime candidates
        5. classify missing vars with current error semantics
        6. interpolate env references
        7. synthesize rendered env
        8. reattach dependency metadata
        """
        svc = self._mcp_preparation_service

        # 4. Strip dependencies for env-ref collection
        mcp_runtime = svc.strip_dependency_metadata(mcp_source_configs)
        if not isinstance(mcp_runtime, dict):
            raise RuntimeError("MCP manifest must remain a mapping after dependency stripping.")

        # 4-5. Collect required env refs and classify missing
        required_vars = svc.collect_env_refs(mcp_runtime) | svc.collect_declared_env_names(
            mcp_source_configs
        )
        missing = sorted(required_vars - runtime_env.env.keys())
        if missing:
            self._raise_missing_env_error(
                missing, runtime_env, selected_dependencies, mcp_server_refs
            )

        # 6. Interpolate env references
        resolved_mcp = svc.resolve_env_refs(mcp_runtime, runtime_env.env)
        if not isinstance(resolved_mcp, dict):
            raise RuntimeError("Resolved MCP manifest must remain a mapping.")

        # 7. Synthesize rendered env from dependencies
        resolved_mcp = svc.synthesize_env_from_dependencies(
            resolved_mcp,
            mcp_source_configs,
            runtime_env.env,
        )

        # 8. Reattach dependency metadata
        resolved_mcp = svc.attach_dependency_metadata(resolved_mcp, mcp_source_configs)

        # Build scoped-ref lookup
        ref_by_server_id: dict[str, tuple[str, str]] = {}
        for ref in mcp_server_refs:
            alias, server_id = split_scoped_ref(ref)
            ref_by_server_id[server_id] = (alias, ref)

        # Convert to PreparedMcpServer entries
        prepared: list[PreparedMcpServer] = []
        for server_id, runtime_config in resolved_mcp.items():
            if not isinstance(runtime_config, dict):
                continue
            alias, scoped_ref = ref_by_server_id.get(server_id, ("unknown", server_id))
            source_config = mcp_source_configs.get(server_id, {})

            env_dependencies: dict[str, EnvDependency] = {}
            deps = runtime_config.get("dependencies") or {}
            if isinstance(deps, dict):
                env_dependencies = {
                    name: dep for name, dep in deps.items() if isinstance(dep, EnvDependency)
                }

            prepared.append(
                PreparedMcpServer(
                    scoped_ref=scoped_ref,
                    source_alias=alias,
                    server_id=server_id,
                    source_config=source_config,
                    runtime_config=runtime_config,
                    env_dependencies=env_dependencies,
                )
            )
        return prepared

    @staticmethod
    def _raise_missing_env_error(
        missing: list[str],
        runtime_env: "RuntimeEnv",
        selected_dependencies: dict[str, EnvDependency],
        mcp_server_refs: list[str],
    ) -> None:
        """Raise a detailed error for unresolved MCP env variables."""

        unfilled_local = [v for v in missing if v in runtime_env.unfilled_local_vars]
        declared_unresolved = [
            v
            for v in missing
            if v not in runtime_env.unfilled_local_vars and v in selected_dependencies
        ]
        undeclared = [
            v
            for v in missing
            if v not in runtime_env.unfilled_local_vars and v not in selected_dependencies
        ]
        parts: list[str] = []
        if unfilled_local:
            for name in unfilled_local:
                cfg = runtime_env.local_vars.get(name)
                hint = f" ({cfg.description})" if cfg and cfg.description else ""
                parts.append(
                    f"{name}{hint} is local-scoped. "
                    "Set its value in .env.ai-sync and re-run."
                )
        if declared_unresolved:
            parts.append(
                "MCP config references env vars declared by selected artifacts but "
                "unresolved at runtime: " + ", ".join(declared_unresolved)
            )
        if undeclared:
            parts.append(
                "MCP config references env vars not declared in selected artifact "
                "dependencies: " + ", ".join(undeclared)
            )
        raise RuntimeError("\n".join(parts))
