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
from .env_config import RuntimeEnv
from .git_safety import SENSITIVE_PATHS
from .helpers import to_kebab_case
from .mcp_sync import resolve_servers_for_client
from .path_ops import escape_path_segment
from .project import ProjectManifest, split_scoped_ref
from .source_resolver import ResolvedSource
from .track_write import WriteSpec

SKIP_PATTERNS = {".venv", "node_modules", "__pycache__", ".git", ".DS_Store"}
BUNDLE_ARTIFACT_FILENAME = "artifact.yaml"
BUNDLE_PROMPT_FILENAME = "prompt.md"


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
    runtime_env: RuntimeEnv,
    mcp_manifest: dict,
    clients: list[Client],
    display: Display,
) -> list[Artifact]:
    return [
        *_agent_artifacts(manifest, resolved_sources, clients, display),
        *_command_artifacts(manifest, resolved_sources, clients, display),
        *_skill_artifacts(manifest, resolved_sources, clients),
        *_rule_artifacts(manifest, resolved_sources, project_root),
        *_client_rule_artifacts(manifest, resolved_sources, clients, display),
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
        agent_rel = Path(agent_name)
        artifact_path = _bundle_entry_path(resolved_sources[alias].root / "prompts", agent_rel)
        if not artifact_path.exists():
            raise RuntimeError(f"Selected agent {agent_ref!r} was not found.")

        meta, _ = _load_artifact_yaml(
            artifact_path,
            defaults={
                "name": to_kebab_case(agent_rel.name),
                "slug": to_kebab_case(agent_rel.name),
            },
            metadata_keys={"slug", "name", "description"},
            required_keys={"description"},
        )
        slug = str(meta.get("slug") or to_kebab_case(agent_rel.name))

        for client in clients:
            prefixed_slug = f"{alias}-{slug}"

            def make_resolve(p=artifact_path, c=client, a=alias, rel=agent_rel):
                def resolve():
                    m, raw_content = _load_artifact_yaml(
                        p,
                        defaults={
                            "name": to_kebab_case(rel.name),
                            "slug": to_kebab_case(rel.name),
                        },
                        metadata_keys={"slug", "name", "description"},
                        required_keys={"description"},
                    )
                    s = str(m.get("slug") or to_kebab_case(rel.name))
                    return c.build_agent_specs(a, s, m, raw_content, _bundle_prompt_path(p))
                return resolve

            if client.name == "codex":
                target = client.get_agents_dir() / prefixed_slug
            elif client.name == "claude":
                target = client.get_agents_dir() / f"{prefixed_slug}.md"
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
    display: Display,
) -> list[Artifact]:
    artifacts: list[Artifact] = []
    for command_ref in manifest.commands:
        alias, command_name = split_scoped_ref(command_ref)
        command_rel = Path(command_name)
        command_path = _bundle_entry_path(resolved_sources[alias].root / "commands", command_rel)
        if not command_path.is_file():
            raise RuntimeError(f"Selected command {command_ref!r} was not found.")

        for client in clients:

            def make_resolve(
                p=command_path,
                c=client,
                a=alias,
                ref=command_ref,
                name=command_rel.as_posix(),
            ):
                def resolve():
                    meta, raw_content = _load_artifact_yaml(
                        p,
                        defaults={},
                        metadata_keys={"description"},
                        required_keys={"description"},
                    )
                    return c.build_command_specs(a, ref, meta, raw_content, name)
                return resolve

            target = _command_target_path(client, alias, command_rel)

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
        artifact_path = skill_dir / "artifact.yaml"
        if not (skill_dir.is_dir() and artifact_path.exists()):
            raise RuntimeError(f"Selected skill {skill_ref!r} was not found.")
        kebab_name = to_kebab_case(Path(skill_name).name)
        prefixed_name = f"{alias}-{kebab_name}"

        for client in clients:
            target_skill_dir = client.get_skills_dir() / prefixed_name

            def make_resolve(ap=artifact_path, sd=skill_dir, kn=kebab_name, tsd=target_skill_dir):
                def resolve():
                    return _build_skill_specs(ap, sd, kn, tsd)
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


def _build_skill_specs(
    artifact_path: Path,
    skill_dir: Path,
    kebab_name: str,
    target_skill_dir: Path,
) -> list[WriteSpec]:
    specs: list[WriteSpec] = []
    meta, prompt = _load_artifact_yaml(
        artifact_path,
        defaults={"name": kebab_name},
        metadata_keys=None,
        required_keys={"description"},
    )
    specs.append(
        WriteSpec(
            file_path=target_skill_dir / "SKILL.md",
            format="text",
            target=f"ai-sync:skill:{kebab_name}:SKILL.md",
            value=_render_skill_markdown(meta, prompt),
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
        rule_path = _bundle_entry_path(resolved_sources[alias].root / "rules", Path(rule_name))
        if not rule_path.exists():
            raise RuntimeError(f"Selected rule {rule_ref!r} was not found.")

        prefixed_name = f"{alias}-{rule_name}"
        target = rules_dir / f"{prefixed_name}.md"
        marker_id = f"ai-sync:rule:{prefixed_name}"

        def make_resolve(p=rule_path, t=target, mid=marker_id):
            def resolve():
                _, content = _load_artifact_yaml(
                    p,
                    defaults={"alwaysApply": True},
                    metadata_keys={"description", "alwaysApply", "globs"},
                    required_keys={"description"},
                )
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


def _client_rule_artifacts(
    manifest: ProjectManifest,
    resolved_sources: dict[str, ResolvedSource],
    clients: list[Client],
    display: Display,
) -> list[Artifact]:
    artifacts: list[Artifact] = []
    for rule_ref in manifest.rules:
        alias, rule_name = split_scoped_ref(rule_ref)
        rule_path = _bundle_entry_path(resolved_sources[alias].root / "rules", Path(rule_name))
        if not rule_path.exists():
            raise RuntimeError(f"Selected rule {rule_ref!r} was not found.")

        prefixed_name = f"{alias}-{rule_name}"
        marker_id = f"ai-sync:rule:{prefixed_name}:client"
        for client in clients:
            if client.name != "claude":
                continue
            target = client.config_dir / "rules" / f"{prefixed_name}.md"

            def make_resolve(p=rule_path, t=target, mid=marker_id):
                def resolve():
                    metadata, content = _load_artifact_yaml(
                        p,
                        defaults={"alwaysApply": True},
                        metadata_keys={"description", "alwaysApply", "globs"},
                        required_keys={"description"},
                    )
                    rendered = _render_claude_rule(content, metadata)
                    return [WriteSpec(file_path=t, format="text", target=mid, value=rendered)]

                return resolve

            artifacts.append(
                Artifact(
                    kind="rule",
                    resource=rule_ref,
                    source_alias=alias,
                    plan_key=str(target),
                    secret_backed=False,
                    resolve_fn=make_resolve(),
                )
            )
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
            elif client.name == "claude":
                target_file = client.config_dir.parent / ".mcp.json"
                plan_key = f"{target_file}#/mcpServers/{prefixed_id}"
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


def _env_artifacts(project_root: Path, runtime_env: RuntimeEnv) -> list[Artifact]:
    if not runtime_env.env and not runtime_env.local_vars:
        return []
    env_path = project_root / ".env.ai-sync"

    def make_resolve(re=runtime_env, ep=env_path):
        def resolve():
            all_keys = set(re.env.keys()) | set(re.local_vars.keys())
            lines = [f"{key}={re.env.get(key, '')}" for key in sorted(all_keys)]
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


def _command_target_path(client: Client, alias: str, command_rel: Path) -> Path:
    if client.name == "gemini":
        return client.config_dir / "commands" / command_rel.with_name(f"{alias}-{command_rel.name}.toml")
    return client.config_dir / "commands" / command_rel.with_name(f"{alias}-{command_rel.name}.md")


def _bundle_entry_path(base_dir: Path, artifact_rel: Path) -> Path:
    return base_dir / artifact_rel / BUNDLE_ARTIFACT_FILENAME


def _bundle_prompt_path(artifact_path: Path) -> Path:
    return artifact_path.with_name(BUNDLE_PROMPT_FILENAME)


def _load_artifact_yaml(
    artifact_path: Path,
    *,
    defaults: dict[str, object],
    metadata_keys: set[str] | None,
    required_keys: set[str],
) -> tuple[dict, str]:
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
    prompt_path = _bundle_prompt_path(artifact_path)
    if not prompt_path.is_file():
        raise RuntimeError(
            f"Artifact bundle {artifact_path.parent} must include {BUNDLE_PROMPT_FILENAME}."
        )
    try:
        prompt = prompt_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(
            f"Failed to load prompt file {prompt_path.name}: {exc}"
        ) from exc
    return result, prompt


def _render_skill_markdown(meta: dict, prompt: str) -> str:
    frontmatter = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
    body = prompt if prompt.endswith("\n") else f"{prompt}\n"
    return f"---\n{frontmatter}\n---\n\n{body}"


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
