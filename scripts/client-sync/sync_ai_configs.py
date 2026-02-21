#!/usr/bin/env python3
"""Sync AI configs (agents, skills, MCP servers, client config) to Codex, Cursor, Gemini."""
from __future__ import annotations

import argparse
import json
import os
import sys
import re
import shutil
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from clients import CLIENTS

RuleStyle = Literal["section", "error", "success", "info"]
PrintStyle = Literal["normal", "dim", "warning", "success", "info"]
PanelStyle = Literal["normal", "error", "success", "info"]


class Display(ABC):
    """Interface for displaying sync output. Core passes plain text; display adds styling."""

    @abstractmethod
    def rule(self, title: str, style: RuleStyle = "section") -> None:
        """Draw a section divider with title."""
        ...

    @abstractmethod
    def print(self, msg: str, style: PrintStyle = "normal") -> None:
        """Print a message."""
        ...

    @abstractmethod
    def panel(self, content: str, *, title: str = "", style: PanelStyle = "normal") -> None:
        """Display content in a panel with optional title."""
        ...

    @abstractmethod
    def table(self, headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> None:
        """Display a table with headers and rows."""
        ...


class PlainDisplay(Display):
    """Plain text output for AI agents and logs."""

    def rule(self, title: str, style: RuleStyle = "section") -> None:
        print(f"--- {title} ---")

    def print(self, msg: str, style: PrintStyle = "normal") -> None:
        if style == "warning":
            print(f"Warning: {msg}")
        else:
            print(msg)

    def panel(self, content: str, *, title: str = "", style: PanelStyle = "normal") -> None:
        if title:
            prefix = "ERROR: " if style == "error" else ""
            print(f"=== {prefix}{title} ===")
        if content:
            print(content)
        if title or content:
            print()

    def table(self, headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> None:
        if not headers and not rows:
            return
        col_widths = [
            max(len(str(h)), max((len(str(r[i])) for r in rows), default=0))
            for i, h in enumerate(headers)
        ]
        fmt = "  ".join(f"{{:<{w}}}" for w in col_widths)
        print(fmt.format(*headers))
        print("-" * (sum(col_widths) + 2 * (len(headers) - 1)))
        for row in rows:
            print(fmt.format(*row))


class RichDisplay(Display):
    """Rich TUI output with colors, panels, and tables."""

    _RULE_STYLES: dict[RuleStyle, str] = {
        "section": "bold cyan",
        "error": "bold red",
        "success": "bold green",
        "info": "bold blue",
    }
    _PRINT_STYLES: dict[PrintStyle, str] = {
        "normal": "",
        "dim": "dim",
        "warning": "yellow",
        "success": "bold green",
        "info": "cyan",
    }
    _PANEL_STYLES: dict[PanelStyle, str] = {
        "normal": "",
        "error": "red",
        "success": "green",
        "info": "blue",
    }

    def __init__(self) -> None:
        self._console = Console()

    def rule(self, title: str, style: RuleStyle = "section") -> None:
        s = self._RULE_STYLES[style]
        self._console.rule(f"[{s}]{title}[/{s}]")

    def print(self, msg: str, style: PrintStyle = "normal") -> None:
        s = self._PRINT_STYLES[style]
        self._console.print(f"[{s}]{msg}[/{s}]" if s else msg)

    def panel(self, content: str, *, title: str = "", style: PanelStyle = "normal") -> None:
        border = self._PANEL_STYLES[style] or None
        title_str = f"[bold]{title}[/bold]" if title else None
        self._console.print(Panel(content, title=title_str, border_style=border))

    def table(self, headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> None:
        t = Table(show_header=True, header_style="bold", box=None)
        for h in headers:
            t.add_column(h)
        for row in rows:
            t.add_row(*row)
        self._console.print(t)


# Injected at startup in main() based on --plain (default before injection)
display: Display = RichDisplay()


from helpers import (
    backup_context,
    copy_file_if_different,
    ensure_dir,
    extract_description,
    sync_tree_if_different,
    to_kebab_case,
)

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


@dataclass
class SyncOptions:
    """User choices from interactive prompts or defaults when non-interactive."""

    agent_stems: frozenset[str]  # prompt stem (e.g. "cloud_infrastructure_engineer")
    skill_names: frozenset[str]  # skill dir name (e.g. "complexity-scan")
    install_settings: bool
    use_backups: bool
    clear_first: bool


GENERIC_METADATA_KEYS = {"slug", "name", "description"}
VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def _run_interactive_prompts(
    agent_stems: list[str],
    skill_names: list[str],
    *,
    clear_default: bool = False,
) -> SyncOptions | None:
    """Show selection panels and yes/no prompts. Returns None if user cancels."""
    import questionary

    display.print("")
    display.panel("Space to toggle, Enter to confirm", title="Select agents to install", style="info")
    choices = [questionary.Choice(title=a, value=a, checked=True) for a in agent_stems]
    selected_agents = questionary.checkbox("Agents", choices=choices).ask()
    if selected_agents is None:
        return None
    if not selected_agents:
        selected_agents = []

    display.print("")
    display.panel("Space to toggle, Enter to confirm", title="Select skills to install", style="info")
    choices = [questionary.Choice(title=s, value=s, checked=True) for s in skill_names]
    selected_skills = questionary.checkbox("Skills", choices=choices).ask()
    if selected_skills is None:
        return None
    if not selected_skills:
        selected_skills = []

    display.print("")
    display.panel("", title="Sync options", style="info")
    install_settings = questionary.confirm("Install client settings (settings.yaml)?", default=True).ask()
    if install_settings is None:
        return None

    use_backups = questionary.confirm("Create backups before overwriting?", default=True).ask()
    if use_backups is None:
        return None

    clear_first = questionary.confirm("Clear existing setups before syncing?", default=clear_default).ask()
    if clear_first is None:
        return None

    return SyncOptions(
        agent_stems=frozenset(selected_agents),
        skill_names=frozenset(selected_skills),
        install_settings=install_settings,
        use_backups=use_backups,
        clear_first=clear_first,
    )


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
            display.print(f"Failed to load metadata for {prompt_path.name}: {e}", style="warning")

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


def _check_installed_tools() -> list[str]:
    """Check that required tools are installed. Returns list of error messages (empty if ok)."""
    errors: list[str] = []

    # uvx
    if not shutil.which("uvx"):
        errors.append("uvx not found (install uv: https://docs.astral.sh/uv/)")

    # docker
    if not shutil.which("docker"):
        errors.append("docker not found (install Docker Desktop or docker CLI)")

    # node > 20 with npm
    node_path = shutil.which("node")
    if not node_path:
        errors.append("node not found (install Node.js > 20)")
    else:
        output = _run(["node", "--version"])
        node_ver = output.strip().lstrip("v")
        match = VERSION_RE.match(node_ver)
        if match:
            major = int(match.group(1))
            if major < 20:
                errors.append(f"node {major} found; node >= 20 required")
        else:
            errors.append("could not parse node version")
        if not shutil.which("npm"):
            errors.append("npm not found (comes with Node.js)")

    # brew
    if not shutil.which("brew"):
        errors.append("brew not found (install Homebrew: https://brew.sh)")

    return errors


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
            return (
                False,
                f"Version mismatch: {client} expected {exp_match.group(1)}.{exp_match.group(2)}.x "
                f"got {current[client]}",
            )
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
        display.print(f"Failed to load {servers_path}: {e}", style="warning")
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
        display.print(f"Failed to load {secrets_path}: {e}", style="warning")
        return {"servers": {}}


def _for_client(srv: dict, client_name: str) -> bool:
    """Filter: is this server enabled for this client?"""
    if not srv.get("enabled", True):
        return False
    clients = srv.get("clients")
    return clients is None or client_name in (clients or [])


def sync_agents(*, only_stems: frozenset[str] | None = None) -> None:
    display.rule("Syncing Agents")
    prompts = sorted(SOURCE_PROMPTS.glob("*.md"))
    if only_stems is not None:
        prompts = [p for p in prompts if p.stem in only_stems]
    if not prompts:
        display.print("No agents selected", style="dim")
        return

    if not (SOURCE_CLIENT_CONFIG / "settings.yaml").exists():
        gemini = next((c for c in CLIENTS if c.name == "gemini"), None)
        if gemini and hasattr(gemini, "enable_subagents_fallback"):
            gemini.enable_subagents_fallback()

    headers = ("Agent", "Slug", "Clients")
    rows: list[tuple[str, ...]] = []
    for prompt_path in prompts:
        agent_name = prompt_path.stem
        kebab_name = to_kebab_case(agent_name)
        raw_content = prompt_path.read_text(encoding="utf-8")
        meta = get_metadata(prompt_path, raw_content)
        slug = meta.get("slug", kebab_name)
        client_names = ", ".join(c.name for c in CLIENTS)
        rows.append((agent_name, kebab_name, client_names))
        for client in CLIENTS:
            client.write_agent(slug, meta, raw_content, prompt_path)
    display.table(headers, rows)


def sync_skills(*, only_names: frozenset[str] | None = None) -> None:
    display.rule("Syncing Skills")
    skill_dirs = sorted(
        d for d in SOURCE_SKILLS.iterdir() if d.is_dir() and (d / "SKILL.md").exists()
    )
    if only_names is not None:
        skill_dirs = [d for d in skill_dirs if d.name in only_names]
    if not skill_dirs:
        display.print("No skills selected", style="dim")
        return

    headers = ("Skill", "Slug", "Clients")
    rows: list[tuple[str, ...]] = []
    for skill_dir in skill_dirs:
        skill_name = skill_dir.name
        kebab_name = to_kebab_case(skill_name)
        client_names = ", ".join(c.name for c in CLIENTS)
        rows.append((skill_name, kebab_name, client_names))
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
    display.table(headers, rows)


def sync_mcp_servers() -> None:
    if not SOURCE_MCP.exists():
        display.print("MCP Servers: skipping (config/mcp-servers/ not found)", style="dim")
        return

    servers = _load_servers()
    if not servers:
        display.print("MCP Servers: skipping (no servers)", style="dim")
        return

    display.rule("Syncing MCP Servers")
    secrets = _load_secrets()
    if not secrets.get("servers"):
        display.print("No secrets/secrets.yaml found; env/auth will be empty.", style="warning")

    server_ids = [sid for sid, srv in servers.items() if srv.get("enabled", True)]
    for client in CLIENTS:
        client.sync_mcp(servers, secrets, _for_client)
    display.table(
        ("Item", "Value"),
        [
            ("Servers", ", ".join(server_ids) if server_ids else "—"),
            ("Clients", ", ".join(c.name for c in CLIENTS)),
        ],
    )

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
        display.print("Client Config: skipping (config/client-settings/settings.yaml not found)", style="dim")
        return

    display.rule("Syncing Client Config")
    try:
        with open(settings_path, "r", encoding="utf-8") as f:
            settings = yaml.safe_load(f)
    except (yaml.YAMLError, OSError) as e:
        display.print(f"Failed to load {settings_path}: {e}", style="warning")
        return

    settings = settings or {}
    rows: list[tuple[str, ...]] = []
    for client in CLIENTS:
        client.sync_client_config(settings)
        rows.append((client.name, "OK"))
    display.table(("Client", "Status"), rows)


def capture_oauth_cache() -> None:
    display.rule("Capturing OAuth caches")
    secrets_dir = SOURCE_MCP / "secrets"
    ensure_dir(secrets_dir)
    captured: list[str] = []
    for client in CLIENTS:
        src_path = client.get_oauth_src_path()
        stash_name = client.get_oauth_stash_filename()
        if not src_path or not stash_name:
            continue
        if src_path.exists():
            dst = secrets_dir / stash_name
            copy_file_if_different(src_path, dst)
            captured.append(f"{client.name} → {dst.name}")
    if captured:
        for line in captured:
            display.print(f"  ✓ {line}", style="success")
    else:
        display.print("  No OAuth caches to capture", style="dim")
    display.print("Capture complete", style="success")


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
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear completely the agents, skills, and MCP servers in the clients' folders.",
    )
    parser.add_argument(
        "--no-interactive",
        action="store_true",
        help="Skip interactive prompts; sync all agents and skills with default options.",
    )
    parser.add_argument(
        "--plain",
        action="store_true",
        help="Plain text output for AI agents (no Rich TUI). Implies --no-interactive.",
    )
    args = parser.parse_args()

    global display
    display = PlainDisplay() if args.plain else RichDisplay()

    tool_errors = _check_installed_tools()
    if tool_errors:
        err_text = "\n".join(f"  • {e}" for e in tool_errors)
        display.panel(err_text, title="Missing or invalid required tools", style="error")
        print(f"Sync failed: {'; '.join(tool_errors)}", file=sys.stderr)
        return 1

    if args.capture_oauth:
        with backup_context(BACKUP_ROOT_PATH):
            capture_oauth_cache()
        return 0

    if args.force:
        versions = _detect_client_versions()
        if not versions:
            msg = "No client versions detected; ensure codex/cursor/gemini CLIs are on PATH"
            display.panel(
                f"No client versions detected.\n\nPATH={os.environ.get('PATH', '')}\n\n"
                "Ensure codex/cursor/gemini CLIs are installed and on PATH.",
                title="Error",
                style="error",
            )
            print(f"Sync failed: {msg}", file=sys.stderr)
            return 1
        versions_path = CWD / "scripts" / ".client-versions.json"
        versions_path.write_text(json.dumps(versions, indent=2) + "\n", encoding="utf-8")
        display.print(f"✓ Updated {versions_path}", style="success")
    else:
        versions_path = CWD / "scripts" / ".client-versions.json"
        ok, msg = _check_client_versions(versions_path)
        if not ok:
            display.panel(msg, title="Version check failed", style="error")
            print(f"Sync failed: {msg}", file=sys.stderr)
            return 1

    if not SOURCE_PROMPTS.exists() or not SOURCE_SKILLS.exists():
        msg = "config/prompts or config/skills directories not found"
        display.panel(
            "config/prompts or config/skills directories not found.",
            title="Error",
            style="error",
        )
        print(f"Sync failed: {msg}", file=sys.stderr)
        return 1

    agent_stems = sorted(p.stem for p in SOURCE_PROMPTS.glob("*.md"))
    skill_names = sorted(
        d.name for d in SOURCE_SKILLS.iterdir()
        if d.is_dir() and (d / "SKILL.md").exists()
    )
    if not agent_stems and not skill_names:
        msg = "No agents or skills found in config"
        display.panel(
            "No agents or skills found in config.",
            title="Error",
            style="error",
        )
        print(f"Sync failed: {msg}", file=sys.stderr)
        return 1

    if args.no_interactive or args.plain:
        options = SyncOptions(
            agent_stems=frozenset(agent_stems),
            skill_names=frozenset(skill_names),
            install_settings=True,
            use_backups=True,
            clear_first=args.clear,
        )
    else:
        opts = _run_interactive_prompts(agent_stems, skill_names, clear_default=args.clear)
        if opts is None:
            display.print("Cancelled", style="warning")
            print("Sync failed: Cancelled", file=sys.stderr)
            return 1
        options = opts

    display.print("")
    display.rule("Starting Sync", style="info")
    display.print(f"Source: {CWD}", style="info")

    backup_root: Path | None = BACKUP_ROOT_PATH if options.use_backups else None
    if options.clear_first:
        display.rule("Clearing Client Configs", style="error")
        with backup_context(backup_root):
            for client in CLIENTS:
                display.print(f"  Clearing {client.name}...", style="info")
                client.clear()
        display.print("Clear complete", style="success")
        display.print("")

    with backup_context(backup_root):
        sync_agents(only_stems=options.agent_stems)
        sync_skills(only_names=options.skill_names)
        sync_mcp_servers()
        if options.install_settings:
            sync_client_config()

    display.print("")
    display.panel("Sync complete", title="Done", style="success")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as e:
        msg = f"Sync failed: {e}"
        try:
            display.panel(str(e), title="Sync failed", style="error")
        except NameError:
            pass
        print(msg, file=sys.stderr)
        raise SystemExit(1)
