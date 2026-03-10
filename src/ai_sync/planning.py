"""Shared planning pipeline for ai-sync."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from .clients import create_clients
from .display import Display
from .env_loader import collect_env_refs, resolve_env_refs_in_obj
from .helpers import extract_description, to_kebab_case, validate_client_settings
from .manifest_loader import load_and_filter_mcp
from .op_inject import load_runtime_env_from_op
from .project import ProjectManifest, manifest_fingerprint, resolve_project_manifest, split_scoped_ref
from .requirements_checker import check_requirements
from .requirements_loader import load_and_filter_requirements
from .source_resolver import ResolvedSource, resolve_sources

PLAN_SCHEMA_VERSION = 1


class PlanSource(BaseModel):
    alias: str
    source: str
    version: str | None = None
    kind: str
    fingerprint: str
    portability_warning: str | None = None


class PlanAction(BaseModel):
    action: str
    source_alias: str
    kind: str
    resource: str
    target: str
    target_key: str
    secret_backed: bool = False
    composable: bool = False


class ApplyPlan(BaseModel):
    schema_version: int = PLAN_SCHEMA_VERSION
    created_at: str
    project_root: str
    manifest_path: str
    manifest_fingerprint: str
    sources: list[PlanSource] = Field(default_factory=list)
    selections: dict[str, list[str]] = Field(default_factory=dict)
    settings: dict[str, Any] = Field(default_factory=dict)
    actions: list[PlanAction] = Field(default_factory=list)


@dataclass(frozen=True)
class PlanContext:
    plan: ApplyPlan
    manifest: ProjectManifest
    resolved_sources: dict[str, ResolvedSource]
    mcp_manifest: dict
    runtime_env: dict[str, str]
    secrets: dict


def default_plan_path(project_root: Path) -> Path:
    return project_root / ".ai-sync" / "last-plan.yaml"


def save_plan(plan: ApplyPlan, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(plan.model_dump(), sort_keys=False), encoding="utf-8")


def load_plan(path: Path) -> ApplyPlan:
    if not path.exists():
        raise RuntimeError(f"Plan file not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise RuntimeError(f"Failed to parse plan file {path}: {exc}") from exc
    return ApplyPlan.model_validate(data)


def build_plan_context(project_root: Path, config_root: Path | None, display: Display) -> PlanContext:
    manifest = resolve_project_manifest(project_root)
    manifest_path = project_root / ".ai-sync.yaml"
    manifest_hash = manifest_fingerprint(manifest_path)
    resolved_sources = resolve_sources(project_root, manifest)

    errors = validate_client_settings(manifest.settings)
    if errors:
        raise RuntimeError("\n".join(errors))

    mcp_manifest = load_and_filter_mcp(resolved_sources, manifest.mcp_servers, display)
    req_results = check_requirements(load_and_filter_requirements(resolved_sources, manifest.mcp_servers, display))
    for result in req_results:
        if not result.ok and result.error:
            display.print(f"Warning: {result.error}", style="warning")

    runtime_env = _load_runtime_env(resolved_sources, config_root)
    required_vars = collect_env_refs(mcp_manifest)
    missing = sorted(required_vars - runtime_env.keys())
    if missing:
        raise RuntimeError(
            "MCP config references env vars not defined in any selected source template: " + ", ".join(missing)
        )
    if required_vars:
        mcp_manifest = resolve_env_refs_in_obj(mcp_manifest, runtime_env)
    plan = _build_plan(project_root, manifest, manifest_hash, resolved_sources, runtime_env, mcp_manifest, display)
    return PlanContext(
        plan=plan,
        manifest=manifest,
        resolved_sources=resolved_sources,
        mcp_manifest=mcp_manifest,
        runtime_env=runtime_env,
        secrets={"servers": {}},
    )


def validate_saved_plan(path: Path, current: ApplyPlan) -> ApplyPlan:
    saved = load_plan(path)
    if saved.schema_version != PLAN_SCHEMA_VERSION:
        raise RuntimeError(
            f"Plan file schema version {saved.schema_version} is not supported by this ai-sync version."
        )
    if _normalized_plan(saved) != _normalized_plan(current):
        raise RuntimeError(
            "Saved plan is no longer valid. Regenerate it because the manifest, sources, or planned actions changed."
        )
    return saved


def render_plan(plan: ApplyPlan, display: Display) -> None:
    display.print("")
    display.rule("Planned Sources", style="info")
    source_rows = [
        (
            source.alias,
            source.kind,
            source.version or "local",
            source.fingerprint[:12],
        )
        for source in plan.sources
    ]
    if source_rows:
        display.table(("Alias", "Kind", "Version", "Fingerprint"), source_rows)
    else:
        display.print("No sources selected", style="dim")

    warnings = [s for s in plan.sources if s.portability_warning]
    for source in warnings:
        display.print(f"Warning: {source.alias}: {source.portability_warning}", style="warning")

    display.print("")
    display.rule("Planned Actions", style="info")
    action_rows = [
        (
            action.action,
            action.kind,
            action.resource,
            action.target + (" (secret)" if action.secret_backed else ""),
        )
        for action in plan.actions
    ]
    if action_rows:
        display.table(("Action", "Kind", "Resource", "Target"), action_rows)
    else:
        display.print("No planned actions", style="dim")


def _normalized_plan(plan: ApplyPlan) -> dict[str, Any]:
    data = plan.model_dump()
    data.pop("created_at", None)
    return data


def _load_runtime_env(resolved_sources: dict[str, ResolvedSource], config_root: Path | None) -> dict[str, str]:
    runtime_env: dict[str, str] = {}
    owners: dict[str, str] = {}
    for alias in sorted(resolved_sources):
        tpl = resolved_sources[alias].root / ".env.ai-sync.tpl"
        if not tpl.exists():
            continue
        env_values = load_runtime_env_from_op(tpl, config_root)
        for key, value in env_values.items():
            if key in runtime_env and runtime_env[key] != value:
                owner = owners.get(key, "<unknown>")
                raise RuntimeError(
                    f"Environment variable collision for {key!r} across selected sources: {owner!r} and {alias!r}."
                )
            runtime_env[key] = value
            owners[key] = alias
    return runtime_env


def _build_plan(
    project_root: Path,
    manifest: ProjectManifest,
    manifest_hash: str,
    resolved_sources: dict[str, ResolvedSource],
    runtime_env: dict[str, str],
    mcp_manifest: dict,
    display: Display,
) -> ApplyPlan:
    actions: list[PlanAction] = []
    target_owners: dict[str, str] = {}
    clients = create_clients(project_root)

    source_models = [
        PlanSource(
            alias=source.alias,
            source=source.source,
            version=source.version,
            kind=source.kind,
            fingerprint=source.fingerprint,
            portability_warning=source.portability_warning,
        )
        for source in resolved_sources.values()
    ]

    for agent_ref in manifest.agents:
        alias, agent_name = split_scoped_ref(agent_ref)
        source_root = resolved_sources[alias].root
        prompt_path = source_root / "prompts" / f"{agent_name}.md"
        if not prompt_path.exists():
            raise RuntimeError(f"Selected agent {agent_ref!r} was not found.")
        meta = _load_prompt_metadata(prompt_path, display)
        slug = str(meta.get("slug") or to_kebab_case(prompt_path.stem))
        for client in clients:
            if client.name == "codex":
                _append_action(actions, target_owners, "sync", alias, "agent", agent_ref, client.get_agents_dir() / slug / "prompt.md")
                _append_action(
                    actions,
                    target_owners,
                    "sync",
                    alias,
                    "agent",
                    agent_ref,
                    client.get_agents_dir() / slug / "config.toml",
                    target_key=str(client.get_agents_dir() / slug / "config.toml"),
                )
            else:
                _append_action(actions, target_owners, "sync", alias, "agent", agent_ref, client.get_agents_dir() / f"{slug}.md")

    for skill_ref in manifest.skills:
        alias, skill_name = split_scoped_ref(skill_ref)
        skill_dir = resolved_sources[alias].root / "skills" / skill_name
        if not (skill_dir.is_dir() and (skill_dir / "SKILL.md").exists()):
            raise RuntimeError(f"Selected skill {skill_ref!r} was not found.")
        kebab_name = to_kebab_case(skill_name)
        for client in clients:
            _append_action(actions, target_owners, "sync", alias, "skill", skill_ref, client.get_skills_dir() / kebab_name)

    for command_ref in manifest.commands:
        alias, rel_posix = split_scoped_ref(command_ref)
        command_path = resolved_sources[alias].root / "commands" / rel_posix
        if not command_path.is_file():
            raise RuntimeError(f"Selected command {command_ref!r} was not found.")
        rel = Path(rel_posix)
        for client in clients:
            if rel.suffix == ".mdc":
                target = client.config_dir / "rules" / rel
            else:
                target = client.config_dir / "commands" / rel
            _append_action(actions, target_owners, "sync", alias, "command", command_ref, target)

    for rule_ref in manifest.rules:
        alias, rule_name = split_scoped_ref(rule_ref)
        rule_path = resolved_sources[alias].root / "rules" / f"{rule_name}.md"
        if not rule_path.exists():
            raise RuntimeError(f"Selected rule {rule_ref!r} was not found.")
        _append_action(
            actions,
            target_owners,
            "sync",
            alias,
            "rule",
            rule_ref,
            project_root / "AGENTS.md",
            target_key=str(project_root / "AGENTS.md"),
            composable=True,
        )

    for mcp_ref in manifest.mcp_servers:
        alias, server_id = split_scoped_ref(mcp_ref)
        if server_id not in mcp_manifest:
            raise RuntimeError(f"Selected MCP server {mcp_ref!r} was not found.")
        for client in clients:
            if client.name == "codex":
                target = client.config_dir / "config.toml"
                target_key = f"{target}#/mcp_servers/{server_id}"
            else:
                target = client.config_dir / ("settings.json" if client.name == "gemini" else "mcp.json")
                target_key = f"{target}#/mcpServers/{server_id}"
            _append_action(actions, target_owners, "sync", alias, "mcp-server", mcp_ref, target, target_key=target_key)

    if runtime_env:
        _append_action(
            actions,
            target_owners,
            "sync",
            "project",
            "env-file",
            ".env.ai-sync",
            project_root / ".env.ai-sync",
            secret_backed=True,
        )

    if manifest.settings:
        for client in clients:
            target = _client_settings_target(client)
            if target is None:
                continue
            _append_action(actions, target_owners, "sync", "project", "client-settings", client.name, target)

    instructions_path = project_root / ".ai-sync" / "instructions.md"
    if instructions_path.exists() and instructions_path.read_text(encoding="utf-8").strip():
        for client in clients:
            target = _instructions_target(client)
            if target is None:
                continue
            _append_action(actions, target_owners, "sync", "project", "instructions", client.name, target)

    selections = {
        "agents": manifest.agents,
        "skills": manifest.skills,
        "commands": manifest.commands,
        "rules": manifest.rules,
        "mcp-servers": manifest.mcp_servers,
    }
    return ApplyPlan(
        created_at=datetime.now(UTC).isoformat(),
        project_root=str(project_root),
        manifest_path=str(project_root / ".ai-sync.yaml"),
        manifest_fingerprint=manifest_hash,
        sources=sorted(source_models, key=lambda item: item.alias),
        selections=selections,
        settings=manifest.settings,
        actions=actions,
    )


def _append_action(
    actions: list[PlanAction],
    target_owners: dict[str, str],
    action: str,
    source_alias: str,
    kind: str,
    resource: str,
    target: Path,
    *,
    target_key: str | None = None,
    secret_backed: bool = False,
    composable: bool = False,
) -> None:
    key = target_key or str(target)
    owner = target_owners.get(key)
    if owner and not composable:
        raise RuntimeError(
            f"Planning collision: {resource!r} would also write to {key}, already owned by {owner!r}."
        )
    target_owners[key] = resource
    action_type = "update" if target.exists() else "create"
    actions.append(
        PlanAction(
            action=action_type if action == "sync" else action,
            source_alias=source_alias,
            kind=kind,
            resource=resource,
            target=str(target),
            target_key=key,
            secret_backed=secret_backed,
            composable=composable,
        )
    )


def _client_settings_target(client: Any) -> Path | None:
    if client.name == "codex":
        return client.config_dir / "config.toml"
    if client.name == "cursor":
        return client.config_dir / "cli-config.json"
    if client.name == "gemini":
        return client.config_dir / "settings.json"
    return None


def _instructions_target(client: Any) -> Path | None:
    if client.name == "codex":
        return client.config_dir / "config.toml"
    if client.name == "cursor":
        return client.config_dir / "rules" / "instructions.mdc"
    if client.name == "gemini":
        return client.config_dir / "GEMINI.md"
    return None


def _load_prompt_metadata(prompt_path: Path, display: Display) -> dict[str, Any]:
    metadata_path = prompt_path.with_suffix(".metadata.yaml")
    content = prompt_path.read_text(encoding="utf-8")
    result: dict[str, Any] = {
        "name": to_kebab_case(prompt_path.stem),
        "description": extract_description(content),
        "slug": to_kebab_case(prompt_path.stem),
    }
    if not metadata_path.exists():
        return result
    try:
        data = yaml.safe_load(metadata_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        display.print(f"Warning: failed to load metadata for {prompt_path.name}: {exc}", style="warning")
        return result
    if isinstance(data, dict):
        for key in ("slug", "name", "description"):
            if key in data and data[key] is not None:
                result[key] = data[key]
    return result
