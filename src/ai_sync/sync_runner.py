"""Main orchestration for project-scoped apply."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from ai_sync.artifacts import Artifact, collect_artifacts
from ai_sync.clients import Client, create_clients
from ai_sync.display import Display
from ai_sync.env_config import RuntimeEnv
from ai_sync.git_safety import install_pre_commit_hook
from ai_sync.project import ProjectManifest
from ai_sync.source_resolver import ResolvedSource
from ai_sync.state_store import StateStore
from ai_sync.track_write import DELETE, WriteSpec, _is_full_file_target, track_write_blocks


def run_apply(
    *,
    project_root: Path,
    source_roots: Mapping[str, Path],
    manifest: ProjectManifest,
    mcp_manifest: dict,
    secrets: dict,
    runtime_env: RuntimeEnv,
    resolved_sources: dict[str, ResolvedSource],
    display: Display,
) -> int:
    display.print("")
    display.rule("Starting Apply", style="info")

    clients = create_clients(project_root)
    store = StateStore(project_root)
    store.load()

    artifacts = collect_artifacts(
        project_root=project_root,
        manifest=manifest,
        resolved_sources=resolved_sources,
        runtime_env=runtime_env,
        mcp_manifest=mcp_manifest,
        clients=clients,
        display=display,
    )

    all_specs: list[WriteSpec] = []
    desired_targets: set[tuple[str, str, str]] = set()
    secret_file_paths: set[Path] = set()
    spec_metadata: list[tuple[WriteSpec, Artifact]] = []

    for artifact in artifacts:
        specs = artifact.resolve()
        all_specs.extend(specs)
        for spec in specs:
            desired_targets.add((str(spec.file_path), spec.format, spec.target))
            spec_metadata.append((spec, artifact))
        if artifact.secret_backed:
            for spec in specs:
                secret_file_paths.add(spec.file_path)

    if all_specs:
        track_write_blocks(all_specs, store)

    for spec, artifact in spec_metadata:
        entry = store.get_entry(spec.file_path, spec.format, spec.target)
        if entry is not None:
            entry["kind"] = artifact.kind
            entry["resource"] = artifact.resource
            entry["source_alias"] = artifact.source_alias

    stale_delete_specs = _build_stale_delete_specs(store, desired_targets)
    if stale_delete_specs:
        track_write_blocks(stale_delete_specs, store)
        dirs_to_clean: set[Path] = set()
        for spec in stale_delete_specs:
            file_path = spec.file_path
            if str(file_path) in {fp for fp, _, _ in desired_targets}:
                continue
            if file_path.is_file() and not file_path.read_text(encoding="utf-8").strip():
                file_path.unlink(missing_ok=True)
                dirs_to_clean.add(file_path.parent)
            store.remove_entry(file_path, spec.format, spec.target)
        for d in sorted(dirs_to_clean, key=lambda p: len(p.parts), reverse=True):
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()

    for path in secret_file_paths:
        if path.exists():
            Client.set_restrictive_permissions(path)

    has_env = bool(runtime_env.env) or bool(runtime_env.local_vars)
    if has_env:
        installed = install_pre_commit_hook(project_root)
        if installed:
            display.print("  Installed pre-commit hook guarding .env.ai-sync", style="info")

    store.save()

    display.print("")
    display.panel("Apply complete", title="Done", style="success")
    return 0


def _build_stale_delete_specs(
    store: StateStore, desired_targets: set[tuple[str, str, str]]
) -> list[WriteSpec]:
    stale_specs: list[WriteSpec] = []
    desired_targets_by_file: dict[tuple[str, str], set[str]] = {}
    for file_path, fmt, target in desired_targets:
        desired_targets_by_file.setdefault((file_path, fmt), set()).add(target)
    for entry in store.list_entries():
        file_path = entry.get("file_path")
        fmt = entry.get("format")
        target = entry.get("target")
        if not isinstance(file_path, str) or not isinstance(fmt, str) or not isinstance(target, str):
            continue
        if (file_path, fmt, target) in desired_targets:
            continue
        same_file_targets = desired_targets_by_file.get((file_path, fmt), set())
        if _is_full_file_target(target) and any(other != target for other in same_file_targets):
            continue
        stale_specs.append(WriteSpec(file_path=Path(file_path), format=fmt, target=target, value=DELETE))
    return stale_specs
