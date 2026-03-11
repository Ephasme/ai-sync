"""Unified artifact model for ai-sync.

Every syncable item (agent, command, skill, rule, MCP server, env file,
client settings, instructions, gitignore) is represented as an Artifact
with a closure that produces WriteSpecs on demand.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import tomli
import yaml

from .clients.base import Client
from .display import Display
from .git_safety import SENSITIVE_PATHS
from .helpers import extract_description, to_kebab_case
from .mcp_sync import resolve_servers_for_client
from .path_ops import escape_path_segment
from .project import ProjectManifest, split_scoped_ref
from .source_resolver import ResolvedSource
from .track_write import WriteSpec

SKIP_PATTERNS = {".venv", "node_modules", "__pycache__", ".git", ".DS_Store"}

_GENERIC_METADATA_KEYS = {"slug", "name", "description"}


@dataclass(frozen=True)
class Artifact:
    kind: str
    resource: str
    source_alias: str
    plan_key: str
    secret_backed: bool
    resolve_fn: Callable[[], list[WriteSpec]]

    def resolve(self) -> list[WriteSpec]:
        return self.resolve_fn()


def collect_artifacts(
    project_root: Path,
    manifest: ProjectManifest,
    resolved_sources: dict[str, ResolvedSource],
    runtime_env: dict[str, str],
    mcp_manifest: dict,
    clients: list[Client],
    display: Display,
) -> list[Artifact]:
    return [
        *_agent_artifacts(manifest, resolved_sources, clients, display),
        *_command_artifacts(manifest, resolved_sources, clients),
        *_skill_artifacts(manifest, resolved_sources, clients),
        *_rule_artifacts(manifest, resolved_sources, project_root),
        *_rule_index_artifacts(manifest, project_root),
        *_mcp_artifacts(manifest, mcp_manifest, clients),
        *_env_artifacts(project_root, runtime_env),
        *_settings_artifacts(manifest, clients),
        *_instructions_artifacts(project_root, clients),
        *_gitignore_artifacts(project_root),
    ]


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------


def _agent_artifacts(
    manifest: ProjectManifest,
    resolved_sources: dict[str, ResolvedSource],
    clients: list[Client],
    display: Display,
) -> list[Artifact]:
    artifacts: list[Artifact] = []
    for agent_ref in manifest.agents:
        alias, agent_name = split_scoped_ref(agent_ref)
        source_root = resolved_sources[alias].root
        prompt_path = source_root / "prompts" / f"{agent_name}.md"
        if not prompt_path.exists():
            raise RuntimeError(f"Selected agent {agent_ref!r} was not found.")

        raw = prompt_path.read_text(encoding="utf-8")
        meta = _load_prompt_metadata(prompt_path, raw, display)
        slug = str(meta.get("slug") or to_kebab_case(prompt_path.stem))

        for client in clients:
            prefixed_slug = f"{alias}-{slug}"

            def make_resolve(p=prompt_path, c=client, a=alias, d=display):
                def resolve():
                    raw_content = p.read_text(encoding="utf-8")
                    m = _load_prompt_metadata(p, raw_content, d)
                    s = str(m.get("slug") or to_kebab_case(p.stem))
                    return c.build_agent_specs(a, s, m, raw_content, p)
                return resolve

            if client.name == "codex":
                target = client.get_agents_dir() / prefixed_slug
            else:
                target = client.get_agents_dir() / f"{prefixed_slug}.md"

            artifacts.append(Artifact(
                kind="agent",
                resource=agent_ref,
                source_alias=alias,
                plan_key=str(target),
                secret_backed=False,
                resolve_fn=make_resolve(),
            ))
    return artifacts


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def _command_artifacts(
    manifest: ProjectManifest,
    resolved_sources: dict[str, ResolvedSource],
    clients: list[Client],
) -> list[Artifact]:
    artifacts: list[Artifact] = []
    for command_ref in manifest.commands:
        alias, rel_posix = split_scoped_ref(command_ref)
        command_path = resolved_sources[alias].root / "commands" / rel_posix
        if not command_path.is_file():
            raise RuntimeError(f"Selected command {command_ref!r} was not found.")
        rel = Path(rel_posix)

        for client in clients:

            def make_resolve(p=command_path, c=client, a=alias, ref=command_ref, r=rel):
                def resolve():
                    raw_content = p.read_text(encoding="utf-8")
                    return c.build_command_specs(a, ref, raw_content, r)
                return resolve

            prefixed = rel.with_name(f"{alias}-{rel.name}")
            if rel.suffix == ".mdc":
                target = client.config_dir / "rules" / prefixed
            else:
                target = client.config_dir / "commands" / prefixed

            artifacts.append(Artifact(
                kind="command",
                resource=command_ref,
                source_alias=alias,
                plan_key=str(target),
                secret_backed=False,
                resolve_fn=make_resolve(),
            ))
    return artifacts


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------


def _skill_artifacts(
    manifest: ProjectManifest,
    resolved_sources: dict[str, ResolvedSource],
    clients: list[Client],
) -> list[Artifact]:
    artifacts: list[Artifact] = []
    for skill_ref in manifest.skills:
        alias, skill_name = split_scoped_ref(skill_ref)
        skill_dir = resolved_sources[alias].root / "skills" / skill_name
        if not (skill_dir.is_dir() and (skill_dir / "SKILL.md").exists()):
            raise RuntimeError(f"Selected skill {skill_ref!r} was not found.")
        kebab_name = to_kebab_case(skill_name)
        prefixed_name = f"{alias}-{kebab_name}"

        for client in clients:
            target_skill_dir = client.get_skills_dir() / prefixed_name

            def make_resolve(sd=skill_dir, kn=kebab_name, tsd=target_skill_dir):
                def resolve():
                    return _build_skill_specs(sd, kn, tsd)
                return resolve

            artifacts.append(Artifact(
                kind="skill",
                resource=skill_ref,
                source_alias=alias,
                plan_key=str(target_skill_dir),
                secret_backed=False,
                resolve_fn=make_resolve(),
            ))
    return artifacts


def _build_skill_specs(skill_dir: Path, kebab_name: str, target_skill_dir: Path) -> list[WriteSpec]:
    specs: list[WriteSpec] = []
    for sub in skill_dir.rglob("*"):
        rel = sub.relative_to(skill_dir)
        if any(part in SKIP_PATTERNS for part in rel.parts) or sub.is_dir():
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
    return specs


# ---------------------------------------------------------------------------
# Rules (individual files + index in AGENTS.md)
# ---------------------------------------------------------------------------


def _rule_artifacts(
    manifest: ProjectManifest,
    resolved_sources: dict[str, ResolvedSource],
    project_root: Path,
) -> list[Artifact]:
    artifacts: list[Artifact] = []
    rules_dir = project_root / ".ai-sync" / "rules"

    for rule_ref in manifest.rules:
        alias, rule_name = split_scoped_ref(rule_ref)
        rule_path = resolved_sources[alias].root / "rules" / f"{rule_name}.md"
        if not rule_path.exists():
            raise RuntimeError(f"Selected rule {rule_ref!r} was not found.")

        prefixed_name = f"{alias}-{rule_name}"
        target = rules_dir / f"{prefixed_name}.md"
        marker_id = f"ai-sync:rule:{prefixed_name}"

        def make_resolve(p=rule_path, t=target, mid=marker_id):
            def resolve():
                content = p.read_text(encoding="utf-8")
                return [WriteSpec(file_path=t, format="text", target=mid, value=content)]
            return resolve

        artifacts.append(Artifact(
            kind="rule",
            resource=rule_ref,
            source_alias=alias,
            plan_key=str(target),
            secret_backed=False,
            resolve_fn=make_resolve(),
        ))
    return artifacts


def _rule_index_artifacts(
    manifest: ProjectManifest,
    project_root: Path,
) -> list[Artifact]:
    if not manifest.rules:
        return []

    agents_md = project_root / "AGENTS.md"
    marker_id = "ai-sync:rules-index"

    def make_resolve(rules=list(manifest.rules), pr=project_root):
        def resolve():
            lines = ["## ai-sync Rules (managed)\n", "You MUST read and follow ALL rules listed below:\n"]
            for rule_ref in rules:
                alias, rule_name = split_scoped_ref(rule_ref)
                prefixed = f"{alias}-{rule_name}"
                rel_path = f".ai-sync/rules/{prefixed}.md"
                lines.append(f"- [{rule_name}]({rel_path})")
            content = "\n".join(lines) + "\n"
            return [WriteSpec(
                file_path=pr / "AGENTS.md",
                format="text",
                target=marker_id,
                value=content,
            )]
        return resolve

    return [Artifact(
        kind="rule-index",
        resource="ai-sync:rules-index",
        source_alias="project",
        plan_key=f"{agents_md}#{marker_id}",
        secret_backed=False,
        resolve_fn=make_resolve(),
    )]


# ---------------------------------------------------------------------------
# MCP servers
# ---------------------------------------------------------------------------


def _mcp_artifacts(
    manifest: ProjectManifest,
    mcp_manifest: dict,
    clients: list[Client],
) -> list[Artifact]:
    artifacts: list[Artifact] = []
    for client in clients:
        client_servers = resolve_servers_for_client(mcp_manifest, client.name)
        for mcp_ref in manifest.mcp_servers:
            alias, server_id = split_scoped_ref(mcp_ref)
            server_config = client_servers.get(server_id)
            if server_config is None:
                continue
            prefixed_id = f"{alias}-{server_id}"

            def make_resolve(c=client, pid=prefixed_id, srv=server_config):
                def resolve():
                    return c.build_mcp_specs({pid: srv}, {"servers": {}})
                return resolve

            if client.name == "codex":
                target_file = client.config_dir / "config.toml"
                plan_key = f"{target_file}#/mcp_servers/{prefixed_id}"
            else:
                target_file = client.config_dir / ("mcp.json" if client.name == "cursor" else "settings.json")
                plan_key = f"{target_file}#/mcpServers/{prefixed_id}"

            has_secrets = bool(
                server_config.get("env")
                or server_config.get("auth")
                or server_config.get("oauth")
            )

            artifacts.append(Artifact(
                kind="mcp-server",
                resource=mcp_ref,
                source_alias=alias,
                plan_key=plan_key,
                secret_backed=has_secrets,
                resolve_fn=make_resolve(),
            ))
    return artifacts


# ---------------------------------------------------------------------------
# Environment file
# ---------------------------------------------------------------------------


def _env_artifacts(project_root: Path, runtime_env: dict[str, str]) -> list[Artifact]:
    if not runtime_env:
        return []
    env_path = project_root / ".env.ai-sync"

    def make_resolve(re=runtime_env, ep=env_path):
        def resolve():
            lines = [f"{key}={value}" for key, value in sorted(re.items())]
            content = "\n".join(lines) + "\n"
            return [WriteSpec(file_path=ep, format="text", target="ai-sync:env", value=content)]
        return resolve

    return [Artifact(
        kind="env-file",
        resource=".env.ai-sync",
        source_alias="project",
        plan_key=str(env_path),
        secret_backed=True,
        resolve_fn=make_resolve(),
    )]


# ---------------------------------------------------------------------------
# Client settings
# ---------------------------------------------------------------------------


def _settings_artifacts(
    manifest: ProjectManifest,
    clients: list[Client],
) -> list[Artifact]:
    if not manifest.settings:
        return []
    artifacts: list[Artifact] = []
    for client in clients:

        def make_resolve(c=client, s=manifest.settings):
            def resolve():
                return c.build_client_config_specs(s)
            return resolve

        specs = client.build_client_config_specs(manifest.settings)
        if not specs:
            continue
        target_file = specs[0].file_path
        artifacts.append(Artifact(
            kind="client-settings",
            resource=client.name,
            source_alias="project",
            plan_key=f"{target_file}#settings",
            secret_backed=False,
            resolve_fn=make_resolve(),
        ))
    return artifacts


# ---------------------------------------------------------------------------
# Instructions
# ---------------------------------------------------------------------------


def _instructions_artifacts(project_root: Path, clients: list[Client]) -> list[Artifact]:
    instructions_path = project_root / ".ai-sync" / "instructions.md"
    if not instructions_path.exists():
        return []
    content = instructions_path.read_text(encoding="utf-8")
    if not content.strip():
        return []

    artifacts: list[Artifact] = []
    for client in clients:

        def make_resolve(c=client, ip=instructions_path):
            def resolve():
                text = ip.read_text(encoding="utf-8")
                return c.build_instructions_specs(text)
            return resolve

        specs = client.build_instructions_specs(content)
        if not specs:
            continue
        target_file = specs[0].file_path
        artifacts.append(Artifact(
            kind="instructions",
            resource=client.name,
            source_alias="project",
            plan_key=f"{target_file}#instructions",
            secret_backed=False,
            resolve_fn=make_resolve(),
        ))
    return artifacts


# ---------------------------------------------------------------------------
# Gitignore
# ---------------------------------------------------------------------------


def _gitignore_artifacts(project_root: Path) -> list[Artifact]:
    gitignore_path = project_root / ".gitignore"
    marker_id = "ai-sync:gitignore"

    def make_resolve(gp=gitignore_path):
        def resolve():
            content = "\n".join(SENSITIVE_PATHS) + "\n"
            return [WriteSpec(file_path=gp, format="text", target=marker_id, value=content)]
        return resolve

    return [Artifact(
        kind="git-safety",
        resource=".gitignore entries",
        source_alias="project",
        plan_key=f"{gitignore_path}#{marker_id}",
        secret_backed=False,
        resolve_fn=make_resolve(),
    )]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_prompt_metadata(prompt_path: Path, content: str, display: Display) -> dict:
    metadata_path = prompt_path.with_suffix(".metadata.yaml")
    result: dict = {
        "name": to_kebab_case(prompt_path.stem),
        "description": extract_description(content),
        "slug": to_kebab_case(prompt_path.stem),
    }
    if not metadata_path.exists():
        return result
    try:
        data = yaml.safe_load(metadata_path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError) as exc:
        display.print(f"Warning: failed to load metadata for {prompt_path.name}: {exc}", style="warning")
        return result
    if isinstance(data, dict):
        for key in _GENERIC_METADATA_KEYS:
            if key in data and data[key] is not None:
                result[key] = data[key]
    return result


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
                specs.append(WriteSpec(file_path=file_path, format=fmt, target=prefix or "/", value={}))
                return
            for key, value in node.items():
                next_prefix = f"{prefix}/{escape_path_segment(str(key))}"
                walk(value, next_prefix)
            return
        if isinstance(node, list):
            specs.append(WriteSpec(file_path=file_path, format=fmt, target=prefix or "/", value=[]))
            if not node:
                return
            for idx, value in enumerate(node):
                next_prefix = f"{prefix}/{idx}"
                walk(value, next_prefix)
            return
        specs.append(WriteSpec(file_path=file_path, format=fmt, target=prefix or "/", value=node))

    walk(data, "")
    return specs
