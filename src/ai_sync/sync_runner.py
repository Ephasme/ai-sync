"""Main orchestration for project-scoped apply."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import tomli
import yaml

from ai_sync.clients import Client, create_clients
from ai_sync.display import Display
from ai_sync.helpers import (
    ensure_dir,
    extract_description,
    validate_client_settings,
    to_kebab_case,
)
from ai_sync.mcp_sync import sync_mcp_servers
from ai_sync.project import ProjectManifest
from ai_sync.state_store import StateStore
from ai_sync.track_write import DELETE, WriteSpec, track_write_blocks
from ai_sync.path_ops import escape_path_segment

GENERIC_METADATA_KEYS = {"slug", "name", "description"}
SKIP_PATTERNS = {".venv", "node_modules", "__pycache__", ".git", ".DS_Store"}


def load_prompt_metadata(prompt_path: Path, content: str, display: Display) -> dict:
    metadata_path = prompt_path.with_suffix(".metadata.yaml")
    result: dict = {
        "name": to_kebab_case(prompt_path.stem),
        "description": extract_description(content),
        "reasoning_effort": "high",
        "is_background": False,
        "web_search": True,
        "tools": ["google_web_search"],
    }
    if metadata_path.exists():
        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                user_meta = yaml.safe_load(f)
            if user_meta and isinstance(user_meta, dict):
                for key in GENERIC_METADATA_KEYS:
                    if key in user_meta and user_meta[key] is not None:
                        result[key] = user_meta[key]
        except (yaml.YAMLError, OSError) as exc:
            display.print(f"Failed to load metadata for {prompt_path.name}: {exc}", style="warning")
    return result


def sync_agents(
    config_root: Path,
    agent_list: list[str],
    clients: Sequence[Client],
    store: StateStore,
    display: Display,
) -> None:
    display.rule("Syncing Agents")
    source_prompts = config_root / "config" / "prompts"
    if not source_prompts.exists():
        display.print("No agents source found", style="dim")
        return
    prompts = sorted(source_prompts.glob("*.md"))
    prompts = [p for p in prompts if p.stem in agent_list]
    if not prompts:
        display.print("No agents selected", style="dim")
        return

    rows: list[tuple[str, ...]] = []
    for prompt_path in prompts:
        raw_content = prompt_path.read_text(encoding="utf-8")
        meta = load_prompt_metadata(prompt_path, raw_content, display)
        slug = meta.get("slug", to_kebab_case(prompt_path.stem))
        rows.append((prompt_path.stem, to_kebab_case(prompt_path.stem), ", ".join(c.name for c in clients)))
        for client in clients:
            client.write_agent(slug, meta, raw_content, prompt_path, store)
    display.table(("Agent", "Slug", "Clients"), rows)


def sync_skills(
    config_root: Path,
    skill_list: list[str],
    clients: Sequence[Client],
    store: StateStore,
    display: Display,
) -> None:
    display.rule("Syncing Skills")
    source_skills = config_root / "config" / "skills"
    if not source_skills.exists():
        display.print("No skills source found", style="dim")
        return
    skill_dirs = sorted(d for d in source_skills.iterdir() if d.is_dir() and (d / "SKILL.md").exists())
    skill_dirs = [d for d in skill_dirs if d.name in skill_list]
    if not skill_dirs:
        display.print("No skills selected", style="dim")
        return
    rows: list[tuple[str, ...]] = []
    for skill_dir in skill_dirs:
        kebab_name = to_kebab_case(skill_dir.name)
        rows.append((skill_dir.name, kebab_name, ", ".join(c.name for c in clients)))
        for client in clients:
            target_base = client.get_skills_dir()
            ensure_dir(target_base)
            target_skill_dir = target_base / kebab_name
            ensure_dir(target_skill_dir)
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
                    specs.append(
                        WriteSpec(
                            file_path=target,
                            format=fmt,
                            target=marker_id,
                            value=content,
                        )
                    )
                    continue
                data = _parse_structured_content(content, fmt)
                leaf_specs = _flatten_structured_to_specs(target, fmt, data)
                existing_targets = set(store.list_targets(target, fmt, "/"))
                current_targets = {spec.target for spec in leaf_specs}
                for stale_target in sorted(existing_targets - current_targets):
                    leaf_specs.append(
                        WriteSpec(
                            file_path=target,
                            format=fmt,
                            target=stale_target,
                            value=DELETE,
                        )
                    )
                specs.extend(leaf_specs)
            if specs:
                track_write_blocks(specs, store)
    display.table(("Skill", "Slug", "Clients"), rows)


def sync_commands(
    config_root: Path,
    command_list: list[str],
    clients: Sequence[Client],
    store: StateStore,
    display: Display,
) -> None:
    display.rule("Syncing Commands")
    source_commands = config_root / "config" / "commands"
    if not source_commands.exists():
        display.print("No commands source found", style="dim")
        return
    command_files = []
    for command_path in sorted(source_commands.rglob("*")):
        if not command_path.is_file():
            continue
        rel = command_path.relative_to(source_commands)
        if any(part in SKIP_PATTERNS for part in rel.parts):
            continue
        if rel.as_posix() in command_list:
            command_files.append((command_path, rel))
    if not command_files:
        display.print("No commands selected", style="dim")
        return
    rows: list[tuple[str, ...]] = []
    for command_path, rel in command_files:
        raw_content = command_path.read_text(encoding="utf-8")
        slug = rel.as_posix()
        rows.append((slug, ", ".join(c.name for c in clients)))
        for client in clients:
            client.write_command(slug, raw_content, rel, store)
    display.table(("Command", "Clients"), rows)


def sync_client_config(
    settings: dict,
    clients: Sequence[Client],
    store: StateStore,
    display: Display,
) -> None:
    if not settings:
        display.print("Client Config: skipping (no settings)", style="dim")
        return
    display.rule("Syncing Client Config")
    errors = validate_client_settings(settings)
    if errors:
        display.panel("\n".join(errors), title="Invalid Client Config", style="error")
        return
    mode = settings.get("mode") or "normal"
    if mode == "yolo":
        display.panel(
            "mode=yolo grants full access (no sandbox, no approval prompts).",
            title="Warning",
            style="error",
        )
    rows: list[tuple[str, ...]] = []
    for client in clients:
        client.sync_client_config(settings, store)
        rows.append((client.name, "OK"))
    display.table(("Client", "Status"), rows)


def sync_instructions(
    project_root: Path,
    clients: Sequence[Client],
    store: StateStore,
    display: Display,
) -> None:
    instructions_path = project_root / ".ai-sync" / "instructions.md"
    if not instructions_path.exists():
        return
    display.rule("Syncing Instructions")
    content = instructions_path.read_text(encoding="utf-8")
    if not content.strip():
        return
    for client in clients:
        client.sync_instructions(content, store)
    display.print(f"  Synced to {', '.join(c.name for c in clients)}", style="info")


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


def run_apply(
    *,
    project_root: Path,
    config_root: Path,
    manifest: ProjectManifest,
    mcp_manifest: dict,
    secrets: dict,
    display: Display,
) -> int:
    display.print("")
    display.rule("Starting Apply", style="info")
    display.print(f"Project: {project_root}", style="info")
    display.print(f"Registry: {config_root}", style="info")

    clients = create_clients(project_root)
    store = StateStore(project_root)
    store.load()

    sync_agents(config_root, manifest.agents, clients, store, display)
    sync_skills(config_root, manifest.skills, clients, store, display)
    sync_commands(config_root, manifest.commands, clients, store, display)
    sync_mcp_servers(mcp_manifest, clients, secrets, store, display)
    sync_client_config(manifest.settings, clients, store, display)
    sync_instructions(project_root, clients, store, display)

    store.save()

    for client in clients:
        client.post_apply()

    display.print("")
    display.panel("Apply complete", title="Done", style="success")
    return 0
