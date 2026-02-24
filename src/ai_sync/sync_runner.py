"""Main orchestration (preflight + execute)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence, cast

import tomli
import yaml

from ai_sync.clients import CLIENTS
from ai_sync.display import Display
from ai_sync.env_loader import resolve_env_refs_in_obj
from ai_sync.helpers import (
    ensure_dir,
    extract_description,
    validate_client_settings,
    to_kebab_case,
)
from ai_sync.interactive import SyncOptions, run_interactive_prompts
from ai_sync.manifest_loader import load_manifest
from ai_sync.mcp_sync import sync_mcp_servers
from ai_sync.config_store import get_config_root
from ai_sync.op_inject import load_runtime_env_from_op
from ai_sync.precedence import apply_overrides
from ai_sync.path_ops import escape_path_segment
from ai_sync.version_checks import check_client_versions, detect_client_versions, get_default_versions_path
from ai_sync.state_store import StateStore
from ai_sync.track_write import DELETE, WriteSpec, track_write_blocks

GENERIC_METADATA_KEYS = {"slug", "name", "description"}
SKIP_PATTERNS = {".venv", "node_modules", "__pycache__", ".git", ".DS_Store"}


@dataclass
class RunConfig:
    config_root: Path
    source_prompts: Path
    source_skills: Path
    source_mcp: Path
    source_client_config: Path
    source_env_template: Path
    overrides: Sequence[tuple[str, object]]
    options: SyncOptions


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


def sync_agents(config: RunConfig, display: Display) -> None:
    display.rule("Syncing Agents")
    prompts = sorted(config.source_prompts.glob("*.md"))
    prompts = [p for p in prompts if p.stem in config.options.agent_stems]
    if not prompts:
        display.print("No agents selected", style="dim")
        return
    if not (config.source_client_config / "settings.yaml").exists():
        gemini = next((c for c in CLIENTS if c.name == "gemini"), None)
        if gemini:
            gemini.enable_subagents_fallback()

    rows: list[tuple[str, ...]] = []
    for prompt_path in prompts:
        raw_content = prompt_path.read_text(encoding="utf-8")
        meta = load_prompt_metadata(prompt_path, raw_content, display)
        slug = meta.get("slug", to_kebab_case(prompt_path.stem))
        rows.append((prompt_path.stem, to_kebab_case(prompt_path.stem), ", ".join(c.name for c in CLIENTS)))
        for client in CLIENTS:
            client.write_agent(slug, meta, raw_content, prompt_path)
    display.table(("Agent", "Slug", "Clients"), rows)


def sync_skills(config: RunConfig, display: Display) -> None:
    display.rule("Syncing Skills")
    if not config.source_skills.exists():
        display.print("No skills selected", style="dim")
        return
    skill_dirs = sorted(d for d in config.source_skills.iterdir() if d.is_dir() and (d / "SKILL.md").exists())
    skill_dirs = [d for d in skill_dirs if d.name in config.options.skill_names]
    if not skill_dirs:
        display.print("No skills selected", style="dim")
        return
    rows: list[tuple[str, ...]] = []
    for skill_dir in skill_dirs:
        kebab_name = to_kebab_case(skill_dir.name)
        rows.append((skill_dir.name, kebab_name, ", ".join(c.name for c in CLIENTS)))
        for client in CLIENTS:
            target_base = client.get_skills_dir()
            ensure_dir(target_base)
            target_skill_dir = target_base / kebab_name
            ensure_dir(target_skill_dir)
            specs: list[WriteSpec] = []
            store = StateStore()
            store.load()
            for sub in skill_dir.rglob("*"):
                rel = sub.relative_to(skill_dir)
                if any(part in SKIP_PATTERNS for part in rel.parts):
                    continue
                if sub.is_dir():
                    continue
                target = target_skill_dir / rel
                if sub.name.endswith(".json"):
                    format = "json"
                elif sub.name.endswith(".toml"):
                    format = "toml"
                elif sub.name.endswith(".yaml") or sub.name.endswith(".yml"):
                    format = "yaml"
                else:
                    format = "text"
                content = sub.read_text(encoding="utf-8")
                marker_id = f"ai-sync:skill:{kebab_name}:{rel.as_posix()}"
                if format == "text":
                    specs.append(
                        WriteSpec(
                            file_path=target,
                            format=format,
                            target=marker_id,
                            value=content,
                        )
                    )
                    continue
                data = _parse_structured_content(content, format)
                leaf_specs = _flatten_structured_to_specs(target, format, data)
                existing_targets = set(store.list_targets(target, format, "/"))
                current_targets = {spec.target for spec in leaf_specs}
                for stale_target in sorted(existing_targets - current_targets):
                    leaf_specs.append(
                        WriteSpec(
                            file_path=target,
                            format=format,
                            target=stale_target,
                            value=DELETE,
                        )
                    )
                specs.extend(leaf_specs)
            if specs:
                track_write_blocks(specs)
    display.table(("Skill", "Slug", "Clients"), rows)


def _parse_structured_content(content: str, format: str) -> dict | list:
    if not content.strip():
        return {}
    if format == "json":
        return json.loads(content)
    if format == "toml":
        return tomli.loads(content)
    if format == "yaml":
        data = yaml.safe_load(content)
        return data if isinstance(data, (dict, list)) else {}
    raise ValueError(f"Unsupported format: {format}")


def _flatten_structured_to_specs(file_path: Path, format: str, data: object) -> list[WriteSpec]:
    specs: list[WriteSpec] = []

    def walk(node: object, prefix: str) -> None:
        if isinstance(node, dict):
            if not node:
                specs.append(WriteSpec(file_path=file_path, format=format, target=prefix or "/", value={}))
                return
            for key, value in node.items():
                next_prefix = f"{prefix}/{escape_path_segment(str(key))}"
                walk(value, next_prefix)
            return
        if isinstance(node, list):
            specs.append(WriteSpec(file_path=file_path, format=format, target=prefix or "/", value=[]))
            if not node:
                return
            for idx, value in enumerate(node):
                next_prefix = f"{prefix}/{idx}"
                walk(value, next_prefix)
            return
        specs.append(WriteSpec(file_path=file_path, format=format, target=prefix or "/", value=node))

    walk(data, "")
    return specs


def sync_client_config(config: RunConfig, display: Display) -> None:
    settings_path = config.source_client_config / "settings.yaml"
    if not settings_path.exists():
        display.print("Client Config: skipping (~/.ai-sync/config/client-settings/settings.yaml not found)", style="dim")
        return
    display.rule("Syncing Client Config")
    try:
        with open(settings_path, "r", encoding="utf-8") as f:
            settings = yaml.safe_load(f) or {}
    except (yaml.YAMLError, OSError) as exc:
        display.print(f"Failed to load {settings_path}: {exc}", style="warning")
        return
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
    for client in CLIENTS:
        client.sync_client_config(settings)
        rows.append((client.name, "OK"))
    display.table(("Client", "Status"), rows)


def preflight(config: RunConfig, display: Display) -> dict:
    manifest = load_manifest(config.source_mcp, display)
    if config.overrides:
        manifest = apply_overrides(manifest, config.overrides)
    if not manifest:
        return manifest
    runtime_env = load_runtime_env_from_op(config.source_env_template, config.config_root)
    if runtime_env:
        manifest = cast(dict, resolve_env_refs_in_obj(manifest, runtime_env))
    return manifest


def execute(config: RunConfig, manifest: dict, display: Display) -> int:
    display.print("")
    display.rule("Starting Sync", style="info")
    display.print(f"Source: {config.config_root}", style="info")
    sync_agents(config, display)
    sync_skills(config, display)
    sync_mcp_servers(manifest, display)
    if config.options.install_settings:
        sync_client_config(config, display)
    display.print("")
    display.panel("Sync complete", title="Done", style="success")
    return 0


def run_sync(
    *,
    config_root: Path | None = None,
    force: bool,
    no_interactive: bool,
    plain: bool,
    overrides: Sequence[tuple[str, object]],
    display: Display,
) -> int:
    root = config_root or get_config_root()
    versions_path = get_default_versions_path()
    if force:
        versions = detect_client_versions()
        if not versions:
            raise RuntimeError("No client versions detected; ensure codex/cursor/gemini CLIs are on PATH")
        try:
            versions_path.write_text(json.dumps(versions, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            raise RuntimeError(
                f"Failed to write version lock at {versions_path}: {exc}. "
                "Run from a writable source checkout to update."
            ) from exc
        display.print(f"✓ Updated {versions_path}", style="success")
    else:
        ok, msg = check_client_versions(versions_path)
        if not ok:
            raise RuntimeError(msg)
        if msg != "OK":
            display.print(f"Warning: {msg}", style="warning")

    source_prompts = root / "config" / "prompts"
    source_skills = root / "config" / "skills"
    source_mcp = root / "config" / "mcp-servers"
    source_client_config = root / "config" / "client-settings"
    source_env_template = root / ".env.tpl"

    agent_stems = sorted(p.stem for p in source_prompts.glob("*.md")) if source_prompts.exists() else []
    skill_names = sorted(d.name for d in source_skills.iterdir() if d.is_dir() and (d / "SKILL.md").exists()) if source_skills.exists() else []
    if no_interactive or plain:
        options = SyncOptions(
            agent_stems=frozenset(agent_stems),
            skill_names=frozenset(skill_names),
            install_settings=True,
        )
    else:
        opts = run_interactive_prompts(display, agent_stems, skill_names)
        if opts is None:
            raise RuntimeError("Cancelled")
        options = opts

    config = RunConfig(
        config_root=root,
        source_prompts=source_prompts,
        source_skills=source_skills,
        source_mcp=source_mcp,
        source_client_config=source_client_config,
        source_env_template=source_env_template,
        overrides=overrides,
        options=options,
    )
    manifest = preflight(config, display)
    return execute(config, manifest, display)
