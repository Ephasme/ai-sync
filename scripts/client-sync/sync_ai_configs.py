#!/usr/bin/env python3
"""Sync AI configs (agents, skills, MCP servers, client config) to Codex, Cursor, Gemini."""
import argparse
import json
import re
import shutil
import subprocess
import sys
import os
from pathlib import Path

import yaml

from helpers import (
    backup_context,
    copy_file_if_different,
    ensure_dir,
    extract_description,
    sync_tree_if_different,
    to_kebab_case,
    write_content_if_different,
)
from clients import CLIENTS

# --- Constants ---
_SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _SCRIPT_DIR.parent.parent
CWD = PROJECT_ROOT

SOURCE_PROMPTS = CWD / "config" / "prompts"
SOURCE_SKILLS = CWD / "config" / "skills"
SOURCE_MCP = CWD / "config" / "mcp-servers"
SOURCE_CLIENT_CONFIG = CWD / "config" / "client-settings"

BACKUP_ROOT_PATH = CWD / ".sync_backups"
SKIP_PATTERNS = {".venv", "node_modules", "__pycache__", ".git", ".DS_Store"}


GENERIC_METADATA_KEYS = {"slug", "name", "description"}
VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def get_metadata(prompt_path: Path, content: str) -> dict:
    """Load metadata from yaml file or fall back to defaults.

    Metadata is generic (slug, name, description). Client-specific config
    (models, reasoning_effort, is_background, web_search, tools) is derived
    by the sync script per client and not stored in metadata.
    """
    metadata_path = prompt_path.with_suffix(".metadata.yaml")
    result: dict = {
        "name": to_kebab_case(prompt_path.stem),
        "description": extract_description(content),
        "models": {
            "codex": "gpt-5",
            "cursor": "gpt-5.2",
            "gemini": "gemini-2.0-flash-thinking-exp",
        },
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
        except (yaml.YAMLError, OSError) as e:
            print(f"  Warning: Failed to load metadata for {prompt_path.name}: {e}")

    return result


def _run(cmd: list[str]) -> str:
    try:
        proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
        return (proc.stdout or "") + (proc.stderr or "")
    except FileNotFoundError:
        return ""
    except subprocess.CalledProcessError as exc:
        return (exc.stdout or "") + (exc.stderr or "")


def _detect_client_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    commands: dict[str, list[str]] = {
        "codex": ["codex", "--version"],
        "cursor": ["cursor", "--version"],
        "gemini": ["gemini", "--version"],
    }
    # Ensure common install paths are on PATH for discovery.
    path = os.environ.get("PATH", "")
    extra_bins = ["/opt/homebrew/bin", "/usr/local/bin"]
    for extra in extra_bins:
        if extra and extra not in path.split(":"):
            path = f"{extra}:{path}" if path else extra
    os.environ["PATH"] = path

    for name, cmd in commands.items():
        cmd_path = shutil.which(cmd[0])
        if not cmd_path:
            continue
        output = _run([cmd_path, *cmd[1:]])
        if not output.strip():
            continue
        match = VERSION_RE.search(output)
        if not match:
            continue
        versions[name] = f"{match.group(1)}.{match.group(2)}.{match.group(3)}"
    return versions


def _check_client_versions(versions_path: Path) -> tuple[bool, str]:
    if not versions_path.exists():
        return False, f"Missing version lock file: {versions_path}"
    try:
        expected = json.loads(versions_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"Failed to read {versions_path}: {exc}"
    if not isinstance(expected, dict) or not expected:
        return False, f"No versions stored in {versions_path}"

    current = _detect_client_versions()
    if not current:
        return False, "No client versions detected; ensure clients are installed and on PATH"

    for client, expected_version in expected.items():
        if client not in current:
            return False, f"Unable to detect {client} version (command missing or unreadable)"
        exp_match = VERSION_RE.search(str(expected_version))
        cur_match = VERSION_RE.search(str(current[client]))
        if not exp_match or not cur_match:
            return False, f"Invalid version for {client} (expected {expected_version}, got {current[client]})"
        if exp_match.group(1, 2) != cur_match.group(1, 2):
            return False, f"Version mismatch: {client} expected {exp_match.group(1)}.{exp_match.group(2)}.x got {current[client]}"
    return True, "OK"


def _load_servers() -> dict:
    """Load config/mcp-servers/servers.yaml."""
    servers_path = SOURCE_MCP / "servers.yaml"
    if not servers_path.exists():
        return {}
    try:
        with open(servers_path, "r", encoding="utf-8") as f:
            manifest = yaml.safe_load(f)
        return manifest.get("servers") or {}
    except (yaml.YAMLError, OSError) as e:
        print(f"  Warning: Failed to load {servers_path}: {e}")
        return {}


def _load_secrets() -> dict:
    """Load secrets from config/mcp-servers/secrets/secrets.yaml."""
    secrets_path = SOURCE_MCP / "secrets" / "secrets.yaml"
    if not secrets_path.exists():
        return {"servers": {}}
    try:
        with open(secrets_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if data and isinstance(data, dict) else {"servers": {}}
    except (yaml.YAMLError, OSError) as e:
        print(f"  Warning: Failed to load {secrets_path}: {e}")
        return {"servers": {}}


def _for_client(srv: dict, client_name: str) -> bool:
    """Filter: is this server enabled for this client?"""
    if not srv.get("enabled", True):
        return False
    clients = srv.get("clients")
    return clients is None or client_name in (clients or [])


def sync_agents() -> None:
    print("--- Syncing Agents ---")
    prompts = sorted(SOURCE_PROMPTS.glob("*.md"))

    if not (SOURCE_CLIENT_CONFIG / "settings.yaml").exists():
        gemini = next((c for c in CLIENTS if c.name == "gemini"), None)
        if gemini and hasattr(gemini, "enable_subagents_fallback"):
            gemini.enable_subagents_fallback()

    for prompt_path in prompts:
        agent_name = prompt_path.stem
        kebab_name = to_kebab_case(agent_name)
        print(f"Processing Agent: {agent_name} -> {kebab_name}")

        raw_content = prompt_path.read_text(encoding="utf-8")
        meta = get_metadata(prompt_path, raw_content)
        slug = meta.get("slug", kebab_name)

        for client in CLIENTS:
            client.write_agent(slug, meta, raw_content, prompt_path)


def sync_skills() -> None:
    print("\n--- Syncing Skills ---")
    skill_dirs = sorted(
        d for d in SOURCE_SKILLS.iterdir() if d.is_dir() and (d / "SKILL.md").exists()
    )

    for skill_dir in skill_dirs:
        skill_name = skill_dir.name
        kebab_name = to_kebab_case(skill_name)
        print(f"Processing Skill: {skill_name} -> {kebab_name}")

        for client in CLIENTS:
            target_base = client.get_skills_dir()
            if not target_base.exists():
                if target_base.parent.exists():
                    target_base.mkdir()
                else:
                    continue

            target_skill_dir = target_base / kebab_name
            ensure_dir(target_skill_dir)
            copy_file_if_different(
                skill_dir / "SKILL.md", target_skill_dir / "SKILL.md", backup=False
            )

            for sub in skill_dir.iterdir():
                if not sub.is_dir() or sub.name in SKIP_PATTERNS:
                    continue
                sync_tree_if_different(
                    sub, target_skill_dir / sub.name, SKIP_PATTERNS, backup=False
                )


def sync_mcp_servers() -> None:
    if not SOURCE_MCP.exists():
        print("\n--- MCP Servers: skipping (config/mcp-servers/ not found) ---")
        return

    servers = _load_servers()
    if not servers:
        print("\n--- MCP Servers: skipping (no servers) ---")
        return

    print("\n--- Syncing MCP Servers ---")
    secrets = _load_secrets()
    if not secrets.get("servers"):
        print("  Warning: No secrets/secrets.yaml found; env/auth will be empty.")

    server_ids = [sid for sid, srv in servers.items() if srv.get("enabled", True)]
    if server_ids:
        print(f"  Servers: {', '.join(server_ids)}")

    for client in CLIENTS:
        print(f"  Client: {client.name}")
        client.sync_mcp(servers, secrets, _for_client)

    secrets_dir = SOURCE_MCP / "secrets"
    if secrets_dir.exists():
        for client in CLIENTS:
            stash_name = client.get_oauth_stash_filename()
            if not stash_name:
                continue
            stash_path = secrets_dir / stash_name
            dst_path = client.get_oauth_src_path()
            if dst_path and stash_path.exists():
                copy_file_if_different(stash_path, dst_path)


def sync_client_config() -> None:
    settings_path = SOURCE_CLIENT_CONFIG / "settings.yaml"
    if not SOURCE_CLIENT_CONFIG.exists() or not settings_path.exists():
        print("\n--- Client Config: skipping (config/client-settings/settings.yaml not found) ---")
        return

    print("\n--- Syncing Client Config ---")
    try:
        with open(settings_path, "r", encoding="utf-8") as f:
            settings = yaml.safe_load(f)
    except (yaml.YAMLError, OSError) as e:
        print(f"  Warning: Failed to load {settings_path}: {e}")
        return

    settings = settings or {}
    for client in CLIENTS:
        print(f"  Client: {client.name}")
        client.sync_client_config(settings)


def capture_oauth_cache() -> None:
    print("--- Capturing OAuth caches ---")
    secrets_dir = SOURCE_MCP / "secrets"
    ensure_dir(secrets_dir)

    for client in CLIENTS:
        src_path = client.get_oauth_src_path()
        stash_name = client.get_oauth_stash_filename()
        if not src_path or not stash_name:
            continue
        if src_path.exists():
            dst = secrets_dir / stash_name
            copy_file_if_different(src_path, dst)
            print(f"  Captured {client.name} auth -> {dst}")
    print("--- Capture complete ---")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync AI configs (agents, skills, MCP servers) to Codex, Cursor, Gemini."
    )
    parser.add_argument(
        "--capture-oauth",
        action="store_true",
        help="Capture OAuth token caches into config/mcp-servers/secrets/ for portability.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force sync and overwrite scripts/.client-versions.json with local client versions.",
    )
    args = parser.parse_args()

    if args.capture_oauth:
        with backup_context(BACKUP_ROOT_PATH):
            capture_oauth_cache()
        return 0

    if args.force:
        versions = _detect_client_versions()
        if not versions:
            print("Error: No client versions detected; cannot update scripts/.client-versions.json.")
            print(f"PATH={os.environ.get('PATH', '')}")
            print("Ensure codex/cursor/gemini CLIs are installed and on PATH.")
            return 1
        versions_path = CWD / "scripts" / ".client-versions.json"
        versions_path.write_text(json.dumps(versions, indent=2) + "\n", encoding="utf-8")
        print(f"Updated {versions_path}")
    else:
        versions_path = CWD / "scripts" / ".client-versions.json"
        ok, msg = _check_client_versions(versions_path)
        if not ok:
            print(f"Error: {msg}")
            return 1

    print("Starting Sync...")
    print(f"Source: {CWD}")

    if not SOURCE_PROMPTS.exists() or not SOURCE_SKILLS.exists():
        print("Error: Source 'config/prompts' or 'config/skills' directories not found.")
        return 1

    with backup_context(BACKUP_ROOT_PATH):
        sync_agents()
        sync_skills()
        sync_mcp_servers()
        sync_client_config()

    print("\n--- Sync Complete ---")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
