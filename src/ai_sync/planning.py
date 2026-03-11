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
from .mcp_sync import resolve_servers_for_client
from .op_inject import load_runtime_env_from_op
from .path_ops import delete_at_path, set_at_path
from .project import (
    ProjectManifest,
    manifest_fingerprint,
    resolve_project_manifest,
    resolve_project_manifest_path,
    split_scoped_ref,
)
from .requirements_checker import check_requirements
from .requirements_loader import load_and_filter_requirements
from .source_resolver import ResolvedSource, resolve_sources
from .state_store import StateStore
from .sync_runner import (
    ENV_HINT,
    GENERATED_AGENTS_FILENAME,
    RULES_LINK_TARGET,
    SKIP_PATTERNS,
    _flatten_structured_to_specs,
    _parse_structured_content,
    _rules_link_content,
)
from .track_write import (
    DELETE,
    WriteSpec,
    _dump_structured,
    _is_full_file_target,
    _parse_structured,
    _should_use_full_file_text,
    apply_marker_block,
    remove_marker_block,
)

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
    manifest_path = resolve_project_manifest_path(project_root)
    manifest = resolve_project_manifest(project_root)
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
        resolved_mcp_manifest = resolve_env_refs_in_obj(mcp_manifest, runtime_env)
        if not isinstance(resolved_mcp_manifest, dict):
            raise RuntimeError("Resolved MCP manifest must remain a mapping.")
        mcp_manifest = resolved_mcp_manifest
    plan = _build_plan(
        project_root,
        manifest_path,
        manifest,
        manifest_hash,
        resolved_sources,
        runtime_env,
        mcp_manifest,
        display,
    )
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


def _classify_text_specs(file_path: Path, specs: list[WriteSpec], store: StateStore) -> str:
    original = file_path.read_text(encoding="utf-8") if file_path.exists() else ""
    content = original
    if _should_use_full_file_text(specs):
        for spec in specs:
            if spec.value is DELETE:
                entry = store.get_entry(file_path, "text", spec.target) or {}
                baseline = entry.get("baseline", {}) if isinstance(entry, dict) else {}
                if baseline.get("exists"):
                    blob_id = baseline.get("blob_id")
                    if isinstance(blob_id, str):
                        restored = store.fetch_blob(blob_id)
                        content = restored if restored is not None else ""
                    else:
                        content = original
                else:
                    content = ""
            else:
                content = str(spec.value)
    else:
        for spec in specs:
            if spec.value is DELETE:
                content = remove_marker_block(content, spec.target, file_path)
            else:
                content = apply_marker_block(content, spec.target, str(spec.value), file_path)
    if content == original:
        return "unchanged"
    if not original and content:
        return "create"
    if original and not content:
        return "delete"
    return "update"


def _classify_structured_specs(file_path: Path, fmt: str, specs: list[WriteSpec]) -> str:
    raw = file_path.read_text(encoding="utf-8") if file_path.exists() else ""
    data: object = _parse_structured(raw, fmt)
    for spec in specs:
        if spec.value is DELETE:
            data = delete_at_path(data, spec.target)
        else:
            data = set_at_path(data, spec.target, spec.value)
    new_content = _dump_structured(data, fmt)
    if new_content == raw:
        return "unchanged"
    if not raw and new_content:
        return "create"
    if raw and not new_content.strip():
        return "delete"
    return "update"


def _aggregate_status(statuses: list[str]) -> str:
    changed = [status for status in statuses if status != "unchanged"]
    if not changed:
        return "unchanged"
    if all(status == "create" for status in changed):
        return "create"
    if all(status == "delete" for status in changed):
        return "delete"
    return "update"


def _classify_plan_key_specs(specs: list[WriteSpec], store: StateStore) -> str:
    if not specs:
        return "unchanged"
    grouped: dict[tuple[str, str], list[WriteSpec]] = {}
    for spec in specs:
        grouped.setdefault((str(spec.file_path), spec.format), []).append(spec)
    statuses: list[str] = []
    for (file_path_str, fmt), file_specs in grouped.items():
        file_path = Path(file_path_str)
        if fmt == "text":
            statuses.append(_classify_text_specs(file_path, file_specs, store))
        else:
            statuses.append(_classify_structured_specs(file_path, fmt, file_specs))
    return _aggregate_status(statuses)


_CODEX_CLIENT_SETTING_TARGETS = {
    "/suppress_unstable_features_warning",
    "/features/multi_agent",
    "/features/child_agents_md",
    "/approval_policy",
    "/sandbox_mode",
}
_CURSOR_CLIENT_SETTING_TARGETS = {"/permissions/allow", "/permissions/deny"}
_GEMINI_CLIENT_SETTING_TARGETS = {
    "/experimental/plan",
    "/experimental/enableAgents",
    "/general/defaultApprovalMode",
    "/tools/sandbox",
}


def _infer_stale_action(entry: dict) -> tuple[str, PlanAction] | None:
    file_path_str = entry.get("file_path")
    fmt = entry.get("format")
    target = entry.get("target")
    if not isinstance(file_path_str, str) or not isinstance(fmt, str) or not isinstance(target, str):
        return None
    file_path = Path(file_path_str)

    if target == "ai-sync:rules":
        plan_key = str(file_path)
        return plan_key, PlanAction(
            action="delete",
            source_alias="project",
            kind="rule",
            resource="ai-sync:rules",
            target=file_path_str,
            target_key=plan_key,
        )
    if target == RULES_LINK_TARGET:
        plan_key = f"{file_path_str}#{RULES_LINK_TARGET}"
        return plan_key, PlanAction(
            action="delete",
            source_alias="project",
            kind="rule-link",
            resource=RULES_LINK_TARGET,
            target=file_path_str,
            target_key=plan_key,
        )
    if target == "ai-sync:env":
        plan_key = file_path_str
        return plan_key, PlanAction(
            action="delete",
            source_alias="project",
            kind="env-file",
            resource=".env.ai-sync",
            target=file_path_str,
            target_key=plan_key,
            secret_backed=True,
        )
    if target.startswith("ai-sync:command:"):
        plan_key = file_path_str
        return plan_key, PlanAction(
            action="delete",
            source_alias="state",
            kind="command",
            resource=target.removeprefix("ai-sync:command:"),
            target=file_path_str,
            target_key=plan_key,
        )
    if target.startswith("ai-sync:agent:"):
        resource = target.removeprefix("ai-sync:agent:")
        if resource.endswith(":prompt"):
            resource = resource.removesuffix(":prompt")
        plan_key = file_path_str
        return plan_key, PlanAction(
            action="delete",
            source_alias="state",
            kind="agent",
            resource=resource,
            target=file_path_str,
            target_key=plan_key,
        )
    if target.startswith("/mcp_servers/") or target.startswith("/mcpServers/"):
        server_id = target.split("/", 2)[2]
        plan_key = f"{file_path_str}#{target}"
        return plan_key, PlanAction(
            action="delete",
            source_alias="state",
            kind="mcp-server",
            resource=server_id,
            target=file_path_str,
            target_key=plan_key,
        )
    if target == "/developer_instructions" or target == "ai-sync:instructions":
        plan_key = file_path_str
        return plan_key, PlanAction(
            action="delete",
            source_alias="project",
            kind="instructions",
            resource=file_path.parent.name.lstrip("."),
            target=file_path_str,
            target_key=plan_key,
        )
    if target == "ai-sync:codex-mcp-env":
        plan_key = f"{file_path_str}#{target}"
        return plan_key, PlanAction(
            action="delete",
            source_alias="project",
            kind="mcp-env",
            resource=file_path.name,
            target=file_path_str,
            target_key=plan_key,
        )
    if "skills" in file_path.parts:
        idx = file_path.parts.index("skills")
        if idx + 1 < len(file_path.parts):
            skill_dir = Path(*file_path.parts[: idx + 2])
            plan_key = str(skill_dir)
            return plan_key, PlanAction(
                action="delete",
                source_alias="state",
                kind="skill",
                resource=file_path.parts[idx + 1],
                target=str(skill_dir),
                target_key=plan_key,
            )
    if target in _CODEX_CLIENT_SETTING_TARGETS and file_path.name == "config.toml" and ".codex" in file_path.parts:
        plan_key = file_path_str
        return plan_key, PlanAction(
            action="delete",
            source_alias="project",
            kind="client-settings",
            resource="codex",
            target=file_path_str,
            target_key=plan_key,
        )
    if target in _CURSOR_CLIENT_SETTING_TARGETS and file_path.name == "cli-config.json":
        plan_key = file_path_str
        return plan_key, PlanAction(
            action="delete",
            source_alias="project",
            kind="client-settings",
            resource="cursor",
            target=file_path_str,
            target_key=plan_key,
        )
    if target in _GEMINI_CLIENT_SETTING_TARGETS and file_path.name == "settings.json" and ".gemini" in file_path.parts:
        plan_key = file_path_str
        return plan_key, PlanAction(
            action="delete",
            source_alias="project",
            kind="client-settings",
            resource="gemini",
            target=file_path_str,
            target_key=plan_key,
        )
    return None


def _collect_desired_specs_by_file(
    *,
    project_root: Path,
    manifest: ProjectManifest,
    resolved_sources: dict[str, ResolvedSource],
    runtime_env: dict[str, str],
    mcp_manifest: dict,
    clients: list[Any],
    display: Display,
) -> tuple[dict[str, list[WriteSpec]], dict[str, list[WriteSpec]]]:
    grouped: dict[str, list[WriteSpec]] = {}
    by_plan_key: dict[str, list[WriteSpec]] = {}

    def add_specs(specs: list[WriteSpec], *, plan_key: str | None = None) -> None:
        for spec in specs:
            grouped.setdefault(str(spec.file_path), []).append(spec)
            key = plan_key or str(spec.file_path)
            by_plan_key.setdefault(key, []).append(spec)

    for agent_ref in manifest.agents:
        alias, agent_name = split_scoped_ref(agent_ref)
        source_root = resolved_sources[alias].root
        prompt_path = source_root / "prompts" / f"{agent_name}.md"
        meta = _load_prompt_metadata(prompt_path, display)
        slug = str(meta.get("slug") or to_kebab_case(prompt_path.stem))
        raw_content = prompt_path.read_text(encoding="utf-8")
        for client in clients:
            agent_specs = client.build_agent_specs(slug, meta, raw_content, prompt_path)
            for spec in agent_specs:
                add_specs([spec], plan_key=str(spec.file_path))

    for skill_ref in manifest.skills:
        alias, skill_name = split_scoped_ref(skill_ref)
        skill_dir = resolved_sources[alias].root / "skills" / skill_name
        kebab_name = to_kebab_case(skill_name)
        for client in clients:
            target_skill_dir = client.get_skills_dir() / kebab_name
            specs: list[WriteSpec] = []
            for sub in skill_dir.rglob("*"):
                rel = sub.relative_to(skill_dir)
                if any(part in SKIP_PATTERNS for part in rel.parts):
                    continue
                if sub.is_dir():
                    continue
                target = target_skill_dir / rel
                if sub.name.endswith(".json"):
                    fmt = "json"
                elif sub.name.endswith(".toml"):
                    fmt = "toml"
                elif sub.name.endswith(".yaml") or sub.name.endswith(".yml"):
                    fmt = "yaml"
                else:
                    fmt = "text"
                content = sub.read_text(encoding="utf-8")
                marker_id = f"ai-sync:skill:{kebab_name}:{rel.as_posix()}"
                if fmt == "text":
                    specs.append(WriteSpec(file_path=target, format=fmt, target=marker_id, value=content))
                    continue
                data = _parse_structured_content(content, fmt)
                specs.extend(_flatten_structured_to_specs(target, fmt, data))
            add_specs(specs, plan_key=str(target_skill_dir))

    for command_ref in manifest.commands:
        alias, rel_posix = split_scoped_ref(command_ref)
        command_path = resolved_sources[alias].root / "commands" / rel_posix
        rel = Path(rel_posix)
        raw_content = command_path.read_text(encoding="utf-8")
        for client in clients:
            command_specs = client.build_command_specs(command_ref, raw_content, rel)
            for spec in command_specs:
                add_specs([spec], plan_key=str(spec.file_path))

    if manifest.rules:
        sections: list[str] = []
        for rule_ref in manifest.rules:
            alias, rule_name = split_scoped_ref(rule_ref)
            rule_path = resolved_sources[alias].root / "rules" / f"{rule_name}.md"
            sections.append(rule_path.read_text(encoding="utf-8").strip())
        parts: list[str] = []
        if runtime_env:
            parts.append(ENV_HINT)
        parts.extend(sections)
        add_specs(
            [
                WriteSpec(
                    file_path=project_root / GENERATED_AGENTS_FILENAME,
                    format="text",
                    target="ai-sync:rules",
                    value="\n\n".join(parts) + "\n",
                ),
            ],
            plan_key=str(project_root / GENERATED_AGENTS_FILENAME),
        )
        add_specs(
            [
                WriteSpec(
                    file_path=project_root / "AGENTS.md",
                    format="text",
                    target=RULES_LINK_TARGET,
                    value=_rules_link_content(),
                ),
            ],
            plan_key=f"{project_root / 'AGENTS.md'}#{RULES_LINK_TARGET}",
        )

    for client in clients:
        client_servers = resolve_servers_for_client(mcp_manifest, client.name)
        for spec in client.build_mcp_specs(client_servers, {"servers": {}}):
            if spec.target.startswith("/mcp_servers/") or spec.target.startswith("/mcpServers/"):
                add_specs([spec], plan_key=f"{spec.file_path}#{spec.target}")
            else:
                add_specs([spec], plan_key=f"{spec.file_path}#{spec.target}")

    if runtime_env:
        lines = [f"{key}={value}" for key, value in sorted(runtime_env.items())]
        add_specs(
            [
                WriteSpec(
                    file_path=project_root / ".env.ai-sync",
                    format="text",
                    target="ai-sync:env",
                    value="\n".join(lines) + "\n",
                )
            ],
            plan_key=str(project_root / ".env.ai-sync"),
        )

    if manifest.settings:
        for client in clients:
            setting_specs = client.build_client_config_specs(manifest.settings)
            if setting_specs:
                add_specs(setting_specs, plan_key=str(setting_specs[0].file_path))

    instructions_path = project_root / ".ai-sync" / "instructions.md"
    if instructions_path.exists() and instructions_path.read_text(encoding="utf-8").strip():
        instructions_content = instructions_path.read_text(encoding="utf-8")
        for client in clients:
            instruction_specs = client.build_instructions_specs(instructions_content)
            if instruction_specs:
                add_specs(instruction_specs, plan_key=str(instruction_specs[0].file_path))

    return grouped, by_plan_key


def _compute_target_actions(
    *,
    project_root: Path,
    manifest: ProjectManifest,
    resolved_sources: dict[str, ResolvedSource],
    runtime_env: dict[str, str],
    mcp_manifest: dict,
    clients: list[Any],
    display: Display,
) -> tuple[dict[str, str], list[PlanAction]]:
    desired_specs_by_file, desired_specs_by_plan_key = _collect_desired_specs_by_file(
        project_root=project_root,
        manifest=manifest,
        resolved_sources=resolved_sources,
        runtime_env=runtime_env,
        mcp_manifest=mcp_manifest,
        clients=clients,
        display=display,
    )
    desired_targets = {
        (str(spec.file_path), spec.format, spec.target)
        for specs in desired_specs_by_file.values()
        for spec in specs
    }
    desired_targets_by_file: dict[tuple[str, str], set[str]] = {}
    for file_path, fmt, target in desired_targets:
        desired_targets_by_file.setdefault((file_path, fmt), set()).add(target)
    store = StateStore(project_root)
    store.load()

    stale_specs_by_plan_key: dict[str, list[WriteSpec]] = {}
    delete_actions_by_plan_key: dict[str, PlanAction] = {}
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
        inferred = _infer_stale_action(entry)
        if inferred is None:
            continue
        plan_key, delete_action = inferred
        stale_specs_by_plan_key.setdefault(plan_key, []).append(
            WriteSpec(file_path=Path(file_path), format=fmt, target=target, value=DELETE)
        )
        delete_actions_by_plan_key.setdefault(plan_key, delete_action)

    statuses: dict[str, str] = {}
    for plan_key, specs in desired_specs_by_plan_key.items():
        statuses[plan_key] = _classify_plan_key_specs(specs + stale_specs_by_plan_key.get(plan_key, []), store)

    delete_actions: list[PlanAction] = []
    for plan_key, delete_action in delete_actions_by_plan_key.items():
        if plan_key in desired_specs_by_plan_key:
            continue
        if _classify_plan_key_specs(stale_specs_by_plan_key.get(plan_key, []), store) != "unchanged":
            delete_actions.append(delete_action)

    return statuses, delete_actions


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
    manifest_path: Path,
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
                _append_action(
                    actions,
                    target_owners,
                    "sync",
                    alias,
                    "agent",
                    agent_ref,
                    client.get_agents_dir() / slug / "prompt.md",
                )
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
                _append_action(
                    actions,
                    target_owners,
                    "sync",
                    alias,
                    "agent",
                    agent_ref,
                    client.get_agents_dir() / f"{slug}.md",
                )

    for skill_ref in manifest.skills:
        alias, skill_name = split_scoped_ref(skill_ref)
        skill_dir = resolved_sources[alias].root / "skills" / skill_name
        if not (skill_dir.is_dir() and (skill_dir / "SKILL.md").exists()):
            raise RuntimeError(f"Selected skill {skill_ref!r} was not found.")
        kebab_name = to_kebab_case(skill_name)
        for client in clients:
            _append_action(
                actions,
                target_owners,
                "sync",
                alias,
                "skill",
                skill_ref,
                client.get_skills_dir() / kebab_name,
            )

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

    generated_rules_path = project_root / "AGENTS.generated.md"
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
            generated_rules_path,
            target_key=str(generated_rules_path),
            composable=True,
        )
    if manifest.rules:
        agents_md_path = project_root / "AGENTS.md"
        _append_action(
            actions,
            target_owners,
            "sync",
            "project",
            "rule-link",
            "ai-sync:rules-link",
            agents_md_path,
            target_key=f"{agents_md_path}#ai-sync:rules-link",
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
    target_actions, delete_actions = _compute_target_actions(
        project_root=project_root,
        manifest=manifest,
        resolved_sources=resolved_sources,
        runtime_env=runtime_env,
        mcp_manifest=mcp_manifest,
        clients=clients,
        display=display,
    )
    filtered_actions = [
        action.model_copy(update={"action": action_type})
        for action in actions
        if (action_type := target_actions.get(action.target_key, "unchanged")) != "unchanged"
    ]
    filtered_actions.extend(delete_actions)
    return ApplyPlan(
        created_at=datetime.now(UTC).isoformat(),
        project_root=str(project_root),
        manifest_path=str(manifest_path),
        manifest_fingerprint=manifest_hash,
        sources=sorted(source_models, key=lambda item: item.alias),
        selections=selections,
        settings=manifest.settings,
        actions=filtered_actions,
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
