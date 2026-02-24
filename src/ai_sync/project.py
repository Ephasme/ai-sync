"""Project manifest loading and resolution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field


class ProjectManifest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    agents: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    commands: list[str] = Field(default_factory=list)
    mcp_servers: list[str] = Field(default_factory=list, validation_alias="mcp-servers", serialization_alias="mcp-servers")
    settings: dict[str, Any] = Field(default_factory=dict)


def _deep_merge_settings(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for k, v in base.items():
        result[k] = dict(v) if isinstance(v, dict) else v
    for k, v in overlay.items():
        if v is None:
            result.pop(k, None)
        elif k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge_settings(result[k], v)
        else:
            result[k] = v
    return result


def _load_yaml_file(path: Path) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (yaml.YAMLError, OSError) as exc:
        raise RuntimeError(f"Failed to load {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"Expected a mapping in {path}, got {type(data).__name__}")
    return data


def resolve_project_manifest(project_root: Path) -> ProjectManifest:
    ai_sync_yaml = project_root / ".ai-sync.yaml"
    if not ai_sync_yaml.exists():
        raise RuntimeError(
            f"No .ai-sync.yaml found in {project_root}. Run `ai-sync init` first."
        )

    base_data = _load_yaml_file(ai_sync_yaml)
    base = ProjectManifest.model_validate(base_data)

    local_yaml = project_root / ".ai-sync.local.yaml"
    if not local_yaml.exists():
        return base

    local_data = _load_yaml_file(local_yaml)
    local = ProjectManifest.model_validate(local_data)

    merged_agents = local.agents if "agents" in local_data else base.agents
    merged_skills = local.skills if "skills" in local_data else base.skills
    merged_commands = local.commands if "commands" in local_data else base.commands
    merged_mcp = local.mcp_servers if "mcp-servers" in local_data else base.mcp_servers
    merged_settings = (
        _deep_merge_settings(base.settings, local.settings)
        if "settings" in local_data
        else base.settings
    )

    return ProjectManifest(
        agents=merged_agents,
        skills=merged_skills,
        commands=merged_commands,
        mcp_servers=merged_mcp,
        settings=merged_settings,
    )


def find_project_root(start: Path | None = None) -> Path | None:
    current = (start or Path.cwd()).resolve()
    while True:
        if (current / ".ai-sync.yaml").exists():
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent


def load_defaults(config_root: Path) -> dict[str, Any]:
    defaults_path = config_root / "config" / "defaults.yaml"
    if not defaults_path.exists():
        return {}
    return _load_yaml_file(defaults_path)


def validate_against_registry(
    manifest: ProjectManifest, config_root: Path
) -> list[str]:
    warnings: list[str] = []
    prompts_dir = config_root / "config" / "prompts"
    if prompts_dir.exists():
        available_agents = {p.stem for p in prompts_dir.glob("*.md")}
        for agent in manifest.agents:
            if agent not in available_agents:
                warnings.append(f"Unknown agent: {agent!r}")

    skills_dir = config_root / "config" / "skills"
    if skills_dir.exists():
        available_skills = {
            d.name for d in skills_dir.iterdir() if d.is_dir() and (d / "SKILL.md").exists()
        }
        for skill in manifest.skills:
            if skill not in available_skills:
                warnings.append(f"Unknown skill: {skill!r}")

    commands_dir = config_root / "config" / "commands"
    if commands_dir.exists():
        available_commands: set[str] = set()
        for cmd_path in commands_dir.rglob("*"):
            if cmd_path.is_file():
                available_commands.add(cmd_path.relative_to(commands_dir).as_posix())
        for command in manifest.commands:
            if command not in available_commands:
                warnings.append(f"Unknown command: {command!r}")

    mcp_path = config_root / "config" / "mcp-servers.yaml"
    if mcp_path.exists():
        try:
            data = _load_yaml_file(mcp_path)
            available_servers = set((data.get("servers") or {}).keys())
        except RuntimeError:
            available_servers = set()
        for server in manifest.mcp_servers:
            if server not in available_servers:
                warnings.append(f"Unknown MCP server: {server!r}")

    return warnings
