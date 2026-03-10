"""CLI entrypoint."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import yaml

from .config_store import DEFAULT_SECRET_PROVIDER, ensure_layout, get_config_root, load_config, write_config
from .display import PlainDisplay, RichDisplay
from .display.base import Display
from .error_handler import LOG_FILENAME, handle_fatal
from .gitignore import check_gitignore
from .planning import build_plan_context, default_plan_path, render_plan, save_plan, validate_saved_plan
from .project import find_project_root, resolve_project_manifest
from .repo_store import (
    SLUG_ERROR_MSG,
    RepoEntry,
    _dest_for_name,
    copy_repo_to_store,
    get_all_repo_roots,
    get_repo_root,
    load_repos,
    save_repos,
    validate_slug,
)
from .sync_runner import run_apply
from .uninstall import run_uninstall
from .version_checks import check_client_versions, get_default_versions_path


@contextmanager
def _clone_remote_repo(repo: str) -> Iterator[Path]:
    """Shallow-clone *repo* (a git URL) into a temp directory and yield the path."""
    with tempfile.TemporaryDirectory(prefix="ai-sync-import-") as tmp:
        clone_path = Path(tmp) / "repo"
        cmd = ["git", "clone", "--depth", "1", repo, str(clone_path)]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise RuntimeError("git not found; install git or provide a local repo path") from exc
        except subprocess.CalledProcessError as exc:
            msg = (exc.stderr or exc.stdout or "").strip()
            raise RuntimeError(f"git clone failed: {msg or repo}") from exc
        yield clone_path


def _load_optional_servers(repo_root: Path) -> dict[str, object]:
    mcp_path = repo_root / "mcp-servers.yaml"
    if not mcp_path.exists():
        return {}
    try:
        with open(mcp_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except (yaml.YAMLError, OSError):
        return {}
    servers = data.get("servers") if isinstance(data, dict) else {}
    return servers if isinstance(servers, dict) else {}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sync AI configs (agents, skills, commands, rules, MCP servers) per-project.",
    )
    subparsers = parser.add_subparsers(dest="command")

    install_parser = subparsers.add_parser("install", help="Initialize ~/.ai-sync bootstrap and store auth settings.")
    install_parser.add_argument("--op-account", metavar="NAME", help="1Password account name (desktop app auth).")
    install_parser.add_argument("--force", action="store_true", help="Overwrite existing config.toml.")

    import_parser = subparsers.add_parser("import", help="Legacy helper: import a config repo into ~/.ai-sync.")
    import_parser.add_argument("--repo", required=True, help="Local path or git URL to import from.")
    import_parser.add_argument(
        "--name",
        required=True,
        metavar="SLUG",
        help="Short slug identifier (e.g. team-config). Pattern: [a-z0-9]([a-z0-9-]*[a-z0-9])?",
    )
    import_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing repo entry with the same name.",
    )

    plan_parser = subparsers.add_parser("plan", help="Resolve sources, render a plan, and save a plan artifact.")
    plan_parser.add_argument("--plain", action="store_true", help="Plain output mode (no interactive prompts).")
    plan_parser.add_argument("--out", metavar="PATH", help="Write the plan artifact to PATH.")

    apply_parser = subparsers.add_parser("apply", help="Apply ai-sync config to the current project.")
    apply_parser.add_argument("--plain", action="store_true", help="Plain output mode (no interactive prompts).")
    apply_parser.add_argument("planfile", nargs="?", help="Optional saved plan file to validate and apply.")

    subparsers.add_parser("doctor", help="Check machine bootstrap and project planning health.")

    uninstall_parser = subparsers.add_parser("uninstall", help="Remove ai-sync managed changes from current project.")
    uninstall_parser.add_argument("--apply", action="store_true", help="Apply uninstall (default is dry-run).")

    return parser


def _run_install(args: argparse.Namespace, display: Display) -> int:
    root = ensure_layout()
    config_path = root / "config.toml"
    if config_path.exists() and not args.force:
        display.panel(
            f"Config already exists: {config_path}\nUse --force to overwrite.",
            title="Already installed",
            style="error",
        )
        return 1

    op_account = args.op_account or os.environ.get("OP_ACCOUNT")
    token = os.environ.get("OP_SERVICE_ACCOUNT_TOKEN")
    if not op_account and not token:
        if sys.stdin.isatty():
            op_account = input("1Password account name (as shown in app): ").strip() or None
        if not op_account:
            display.panel(
                "No 1Password account configured.\n"
                "Provide --op-account NAME, set OP_ACCOUNT, or set OP_SERVICE_ACCOUNT_TOKEN.",
                title="Missing account",
                style="error",
            )
            return 1

    config = {"secret_provider": DEFAULT_SECRET_PROVIDER}
    if op_account:
        config["op_account"] = op_account
    write_config(config, root)
    display.print(f"Wrote {config_path}", style="success")
    return 0


def _run_import(args: argparse.Namespace, display: Display) -> int:
    root = ensure_layout()
    config_path = root / "config.toml"

    if not validate_slug(args.name):
        display.panel(SLUG_ERROR_MSG, title="Invalid name", style="error")
        return 1

    repos = load_repos(root)
    existing_entry = next((e for e in repos if e["name"] == args.name), None)
    if existing_entry is not None and not args.force:
        display.panel(
            f"A repo named {args.name!r} already exists. Use --force to overwrite.",
            title="Name conflict",
            style="error",
        )
        return 1

    # Clean up previously cloned remote copy when force-replacing
    if existing_entry is not None and not Path(existing_entry["source"]).is_absolute():
        shutil.rmtree(_dest_for_name(root, args.name), ignore_errors=True)

    abs_path = Path(args.repo).expanduser().resolve()
    if abs_path.exists():
        entry: RepoEntry = {"name": args.name, "source": str(abs_path)}
        display_location = str(abs_path)
    else:
        with _clone_remote_repo(args.repo) as repo_root:
            copy_repo_to_store(root, args.name, repo_root)
        entry: RepoEntry = {"name": args.name, "source": args.repo}
        display_location = str(_dest_for_name(root, args.name))

    if existing_entry is not None:
        idx = repos.index(existing_entry)
        repos[idx] = entry
    else:
        repos.append(entry)
    save_repos(root, repos)

    pos = repos.index(entry) + 1
    total = len(repos)
    if not config_path.exists():
        display.print("Warning: ~/.ai-sync/config.toml is missing. Run `ai-sync install`.", style="warning")
    non_last = repos[:-1]
    for e in non_last:
        if (get_repo_root(root, e) / "defaults.yaml").exists():
            display.print(
                f"Warning: repo {e['name']!r} has defaults.yaml but is not the highest-priority repo."
                " Its defaults will be ignored.",
                style="warning",
            )
    display.print(
        f"Imported {args.name!r} \u2192 {display_location} (position {pos} of {total})",
        style="success",
    )
    return 0


def _discover_registry(repo_roots: list[Path]) -> tuple[list[str], list[str], list[str], list[str], list[str]]:
    agents_seen: dict[str, str] = {}
    skills_seen: dict[str, str] = {}
    commands_seen: dict[str, str] = {}
    rules_seen: dict[str, str] = {}
    mcp_servers_seen: dict[str, str] = {}

    for repo_root in repo_roots:
        prompts_dir = repo_root / "prompts"
        if prompts_dir.exists():
            for p in prompts_dir.glob("*.md"):
                agents_seen[p.stem] = p.stem

        skills_dir = repo_root / "skills"
        if skills_dir.exists():
            for d in skills_dir.iterdir():
                if d.is_dir() and (d / "SKILL.md").exists():
                    skills_seen[d.name] = d.name

        commands_dir = repo_root / "commands"
        if commands_dir.exists():
            for cmd_path in commands_dir.rglob("*"):
                if cmd_path.is_file() and cmd_path.suffix == ".md":
                    rel = cmd_path.relative_to(commands_dir).as_posix()
                    commands_seen[rel] = rel

        rules_dir = repo_root / "rules"
        if rules_dir.exists():
            for p in rules_dir.glob("*.md"):
                rules_seen[p.stem] = p.stem

        for server_id in _load_optional_servers(repo_root).keys():
            mcp_servers_seen[server_id] = server_id

    return (
        sorted(agents_seen),
        sorted(skills_seen),
        sorted(commands_seen),
        sorted(rules_seen),
        sorted(mcp_servers_seen),
    )


def _discover_artifact_tags(repo_roots: list[Path]) -> dict[str, dict[str, list[str]]]:
    """Return tags for every artifact, keyed by artifact name/path. Last repo wins per artifact."""
    result: dict[str, dict[str, list[str]]] = {
        "agents": {},
        "skills": {},
        "commands": {},
        "rules": {},
        "mcp-servers": {},
    }

    for repo_root in repo_roots:
        prompts_dir = repo_root / "prompts"
        if prompts_dir.exists():
            for meta_path in prompts_dir.glob("*.metadata.yaml"):
                agent_name = meta_path.name.removesuffix(".metadata.yaml")
                with open(meta_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                tags = data.get("tags") or []
                if isinstance(tags, list):
                    result["agents"][agent_name] = tags

        skills_dir = repo_root / "skills"
        if skills_dir.exists():
            for skill_dir in skills_dir.iterdir():
                if not (skill_dir.is_dir() and (skill_dir / "SKILL.md").exists()):
                    continue
                meta_path = skill_dir / "metadata.yaml"
                if not meta_path.exists():
                    continue
                with open(meta_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                tags = data.get("tags") or []
                if isinstance(tags, list):
                    result["skills"][skill_dir.name] = tags

        commands_dir = repo_root / "commands"
        if commands_dir.exists():
            for meta_path in commands_dir.rglob("*.metadata.yaml"):
                stem = meta_path.name.removesuffix(".metadata.yaml")
                with open(meta_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                tags = data.get("tags") or []
                if not isinstance(tags, list):
                    continue
                for cmd_file in meta_path.parent.iterdir():
                    if cmd_file.is_file() and cmd_file.stem == stem and not cmd_file.name.endswith(".metadata.yaml"):
                        cmd_key = cmd_file.relative_to(commands_dir).as_posix()
                        result["commands"][cmd_key] = tags

        rules_dir = repo_root / "rules"
        if rules_dir.exists():
            for meta_path in rules_dir.glob("*.metadata.yaml"):
                rule_name = meta_path.name.removesuffix(".metadata.yaml")
                with open(meta_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                tags = data.get("tags") or []
                if isinstance(tags, list):
                    result["rules"][rule_name] = tags

        for server_id, server_cfg in _load_optional_servers(repo_root).items():
            if isinstance(server_cfg, dict):
                tags = server_cfg.get("tags") or []
                if isinstance(tags, list) and tags:
                    result["mcp-servers"][server_id] = tags

    return result


def _filter_by_tags(artifacts: list[str], artifact_tags: dict[str, list[str]], tags: set[str]) -> list[str]:
    """Return artifacts that have at least one of the given tags (OR logic)."""
    return [a for a in artifacts if tags & set(artifact_tags.get(a) or [])]


def _ensure_installed(config_root: Path, display: Display) -> bool:
    if config_root.exists() and (config_root / "config.toml").exists():
        return True
    display.panel("Run `ai-sync install` first.", title="Not set up", style="error")
    return False


def _run_init(args: argparse.Namespace, config_root: Path, display: Display) -> int:
    display.panel(
        "`ai-sync init` is deprecated in this workflow.\nWrite `.ai-sync.yaml` by hand, then run `ai-sync plan`.",
        title="Deprecated command",
        style="error",
    )
    return 1


def _run_plan(args: argparse.Namespace, config_root: Path, display: Display) -> int:
    if not _ensure_installed(config_root, display):
        return 1
    project_root = find_project_root()
    if project_root is None:
        display.panel("No .ai-sync.yaml found. Create one first.", title="No project", style="error")
        return 1

    uncovered = check_gitignore(project_root)
    if uncovered:
        display.panel(
            "The following ai-sync managed paths are not covered by .gitignore:\n"
            + "\n".join(f"  - {p}" for p in uncovered),
            title="Gitignore gate failed",
            style="error",
        )
        return 1

    versions_path = get_default_versions_path()
    ok, msg = check_client_versions(versions_path)
    if not ok or msg != "OK":
        display.print(f"Warning: {msg}", style="warning")

    context = build_plan_context(project_root, config_root, display)
    render_plan(context.plan, display)
    out_path = Path(args.out).expanduser() if getattr(args, "out", None) else default_plan_path(project_root)
    save_plan(context.plan, out_path)
    display.print(f"Saved plan to {out_path}", style="success")
    return 0


def _run_apply(args: argparse.Namespace, config_root: Path, display: Display) -> int:
    if not _ensure_installed(config_root, display):
        return 1
    project_root = find_project_root()
    if project_root is None:
        display.panel("No .ai-sync.yaml found. Create one first.", title="No project", style="error")
        return 1

    uncovered = check_gitignore(project_root)
    if uncovered:
        display.panel(
            "The following ai-sync managed paths are not covered by .gitignore:\n"
            + "\n".join(f"  - {p}" for p in uncovered)
            + "\n\nAdd them to .gitignore before applying.",
            title="Gitignore gate failed",
            style="error",
        )
        return 1

    versions_path = get_default_versions_path()
    ok, msg = check_client_versions(versions_path)
    if not ok or msg != "OK":
        display.print(f"Warning: {msg}", style="warning")

    context = build_plan_context(project_root, config_root, display)
    planfile = getattr(args, "planfile", None)
    if planfile:
        validate_saved_plan(Path(planfile).expanduser(), context.plan)
        display.print(f"Validated saved plan: {planfile}", style="success")
    else:
        display.print("Applying a fresh plan computed from the current project state.", style="info")
        render_plan(context.plan, display)

    return run_apply(
        project_root=project_root,
        source_roots={alias: source.root for alias, source in context.resolved_sources.items()},
        manifest=context.manifest,
        mcp_manifest=context.mcp_manifest,
        secrets=context.secrets,
        runtime_env=context.runtime_env,
        display=display,
    )


def _run_doctor(config_root: Path, display: Display) -> int:
    display.print(f"Config root: {config_root}")
    if not config_root.exists():
        display.print("  Missing config root. Run `ai-sync install`.", style="warning")
        return 1
    config_path = config_root / "config.toml"
    if not config_path.exists():
        display.print("  Missing config.toml. Run `ai-sync install`.", style="warning")
        return 1

    try:
        config = load_config(config_root)
    except RuntimeError as exc:
        display.print(f"  Failed to read config: {exc}", style="warning")
        return 1

    op_account = os.environ.get("OP_ACCOUNT") or config.get("op_account")
    token = os.environ.get("OP_SERVICE_ACCOUNT_TOKEN")
    if token:
        display.print("  1Password auth: OK (service account token)", style="success")
    elif op_account:
        display.print(f"  1Password auth: OK (OP_ACCOUNT={op_account})", style="success")
    else:
        display.print("  1Password auth: missing (set OP_SERVICE_ACCOUNT_TOKEN or OP_ACCOUNT)", style="warning")
        return 1

    repos = load_repos(config_root)
    if not repos:
        display.print("  No repos imported. Run `ai-sync import`.", style="warning")
    else:
        display.print(f"  Repos ({len(repos)}, last = highest priority):")
        for pos, entry in enumerate(repos, start=1):
            repo_path = get_repo_root(config_root, entry)
            is_local = Path(entry["source"]).is_absolute()
            label = f"{entry['name']} (local)" if is_local else entry["name"]
            if repo_path.exists():
                display.print(f"    {pos}. {label}: OK", style="success")
            else:
                display.print(
                    f"    {pos}. {label}: missing "
                    f"(run `ai-sync import --repo {entry['source']} --name {entry['name']}`)",
                    style="warning",
                )

    project_root = find_project_root()
    if project_root:
        display.print(f"\nProject: {project_root}")
        try:
            manifest = resolve_project_manifest(project_root)
            display.print(f"  .ai-sync.yaml: OK ({len(manifest.sources)} sources declared)", style="success")
        except RuntimeError as exc:
            display.print(f"  .ai-sync.yaml: {exc}", style="warning")
            return 1

        uncovered = check_gitignore(project_root)
        if uncovered:
            display.print(f"  Gitignore: MISSING coverage for {', '.join(uncovered)}", style="warning")
        else:
            display.print("  Gitignore: OK", style="success")

        try:
            context = build_plan_context(project_root, config_root, display)
            display.print(
                f"  Planned: {len(context.plan.actions)} action(s) from {len(context.resolved_sources)} source(s)",
                style="success",
            )
        except RuntimeError as exc:
            display.print(f"  Plan check failed: {exc}", style="warning")
    else:
        display.print("\nNo project found (no .ai-sync.yaml in current directory tree)", style="dim")

    return 0


def _run_uninstall(args: argparse.Namespace, display: Display) -> int:
    project_root = find_project_root()
    if project_root is None:
        display.panel("No .ai-sync.yaml found. Nothing to uninstall.", title="No project", style="error")
        return 1
    return run_uninstall(project_root, apply=bool(args.apply))


ARTIFACT_TYPE_TO_YAML_KEY = {
    "agent": "agents",
    "skill": "skills",
    "command": "commands",
    "rule": "rules",
    "mcp-server": "mcp-servers",
}


def _display_name(name: str) -> str:
    """Strip .md extension for human-friendly display."""
    return name.removesuffix(".md")


def _find_canonical(name: str, items: list[str]) -> str | None:
    """Match *name* against *items*, ignoring .md extensions."""
    bare = name.removesuffix(".md")
    for item in items:
        if item.removesuffix(".md") == bare:
            return item
    return None


def _resolve_artifact_type(
    name: str,
    explicit_type: str | None,
    repo_roots: list[Path],
    display: Display,
) -> tuple[str, str] | None:
    """Resolve artifact type from registry.

    Returns ``(type, canonical_name)`` or *None* on error.
    """
    agents, skills, commands, rules, mcp_servers = _discover_registry(repo_roots)
    registry = {
        "agent": agents, "skill": skills, "command": commands,
        "rule": rules, "mcp-server": mcp_servers,
    }
    found: list[tuple[str, str]] = []
    for art_type, items in registry.items():
        canonical = _find_canonical(name, items)
        if canonical is not None:
            found.append((art_type, canonical))

    if explicit_type:
        canonical = _find_canonical(name, registry[explicit_type])
        if canonical is None:
            display.panel(
                f"{name!r} is not a known {explicit_type} in any imported repo.",
                title="Not found",
                style="error",
            )
            return None
        return explicit_type, canonical

    if not found:
        display.panel(
            f"{name!r} was not found in any imported repo.\n"
            "Use --type to specify the artifact type explicitly.",
            title="Not found",
            style="error",
        )
        return None

    if len(found) > 1:
        types_str = ", ".join(t for t, _ in found)
        display.panel(
            f"{name!r} exists as multiple types: {types_str}.\n"
            f"Use --type to disambiguate, e.g.: "
            f"ai-sync add {name} --type={found[0][0]}",
            title="Ambiguous name",
            style="error",
        )
        return None

    return found[0]


def _resolve_artifact_type_from_manifest(
    name: str,
    explicit_type: str | None,
    manifest_data: dict,
    display: Display,
) -> tuple[str, str] | None:
    """Resolve artifact type from the current manifest.

    Returns ``(type, canonical_name)`` or *None* on error.
    """
    found: list[tuple[str, str]] = []
    for art_type, yaml_key in ARTIFACT_TYPE_TO_YAML_KEY.items():
        canonical = _find_canonical(name, manifest_data.get(yaml_key) or [])
        if canonical is not None:
            found.append((art_type, canonical))

    if explicit_type:
        yaml_key = ARTIFACT_TYPE_TO_YAML_KEY[explicit_type]
        canonical = _find_canonical(name, manifest_data.get(yaml_key) or [])
        if canonical is None:
            display.panel(
                f"{name!r} is not in the manifest as a {explicit_type}.",
                title="Not found",
                style="error",
            )
            return None
        return explicit_type, canonical

    if not found:
        display.panel(
            f"{name!r} is not in the manifest.\n"
            "Use --type to specify the artifact type explicitly.",
            title="Not found",
            style="error",
        )
        return None

    if len(found) > 1:
        types_str = ", ".join(t for t, _ in found)
        display.panel(
            f"{name!r} exists as multiple types in the manifest: "
            f"{types_str}.\nUse --type to disambiguate, e.g.: "
            f"ai-sync remove {name} --type={found[0][0]}",
            title="Ambiguous name",
            style="error",
        )
        return None

    return found[0]


def _edit_manifest_and_apply(
    project_root: Path,
    config_root: Path,
    yaml_key: str,
    name: str,
    action: str,
    display: Display,
) -> int:
    """Add or remove *name* from *yaml_key* in .ai-sync.yaml, then run apply."""
    ai_sync_yaml = project_root / ".ai-sync.yaml"
    data = yaml.safe_load(ai_sync_yaml.read_text(encoding="utf-8")) or {}
    items: list[str] = data.get(yaml_key) or []

    if action == "add":
        if name in items:
            display.print(f"{name!r} is already in {yaml_key}.", style="dim")
        else:
            items.append(name)
            data[yaml_key] = items
            with open(ai_sync_yaml, "w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, sort_keys=False, default_flow_style=False)
            display.print(f"Added {name!r} to {yaml_key} in .ai-sync.yaml", style="success")
    elif action == "remove":
        if name not in items:
            display.print(f"{name!r} is not in {yaml_key}.", style="dim")
            return 0
        items.remove(name)
        data[yaml_key] = items
        with open(ai_sync_yaml, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, sort_keys=False, default_flow_style=False)
        display.print(f"Removed {name!r} from {yaml_key} in .ai-sync.yaml", style="success")

    args = argparse.Namespace(plain=False)
    return _run_apply(args, config_root, display)


def _run_add(args: argparse.Namespace, config_root: Path, display: Display) -> int:
    if not config_root.exists() or not (config_root / "config.toml").exists():
        display.panel("Run `ai-sync install` first.", title="Not set up", style="error")
        return 1
    repo_roots = get_all_repo_roots(config_root)
    if not repo_roots:
        display.panel("No repos imported. Run `ai-sync import` first.", title="No repos", style="error")
        return 1
    project_root = find_project_root()
    if project_root is None:
        display.panel("No .ai-sync.yaml found. Run `ai-sync init` first.", title="No project", style="error")
        return 1

    result = _resolve_artifact_type(args.name, args.type, repo_roots, display)
    if result is None:
        return 1
    art_type, canonical = result

    yaml_key = ARTIFACT_TYPE_TO_YAML_KEY[art_type]
    display.print(f"Resolved {_display_name(args.name)!r} as {art_type}", style="info")
    return _edit_manifest_and_apply(project_root, config_root, yaml_key, canonical, "add", display)


def _run_remove(args: argparse.Namespace, config_root: Path, display: Display) -> int:
    project_root = find_project_root()
    if project_root is None:
        display.panel("No .ai-sync.yaml found. Run `ai-sync init` first.", title="No project", style="error")
        return 1

    ai_sync_yaml = project_root / ".ai-sync.yaml"
    manifest_data = yaml.safe_load(ai_sync_yaml.read_text(encoding="utf-8")) or {}

    result = _resolve_artifact_type_from_manifest(args.name, args.type, manifest_data, display)
    if result is None:
        return 1
    art_type, canonical = result

    config_root_check = get_config_root()
    yaml_key = ARTIFACT_TYPE_TO_YAML_KEY[art_type]
    display.print(f"Resolved {_display_name(args.name)!r} as {art_type}", style="info")
    return _edit_manifest_and_apply(project_root, config_root_check, yaml_key, canonical, "remove", display)


def _run_list(args: argparse.Namespace, config_root: Path, display: Display) -> int:
    if args.installed:
        project_root = find_project_root()
        if project_root is None:
            display.panel(
                "No .ai-sync.yaml found. Run `ai-sync init` first.",
                title="No project",
                style="error",
            )
            return 1
        manifest = resolve_project_manifest(project_root)
        sections: dict[str, list[str]] = {
            "Agents": manifest.agents,
            "Skills": manifest.skills,
            "Commands": manifest.commands,
            "Rules": manifest.rules,
            "MCP Servers": manifest.mcp_servers,
        }
        display.print("Installed artifacts:", style="info")
    else:
        if not config_root.exists() or not (config_root / "config.toml").exists():
            display.panel("Run `ai-sync install` first.", title="Not set up", style="error")
            return 1
        repo_roots = get_all_repo_roots(config_root)
        if not repo_roots:
            display.panel("No repos imported. Run `ai-sync import` first.", title="No repos", style="error")
            return 1
        agents, skills, commands, rules, mcp_servers = _discover_registry(repo_roots)

        installed_names: set[str] = set()
        project_root = find_project_root()
        if project_root is not None:
            try:
                m = resolve_project_manifest(project_root)
                for n in (
                    *m.agents, *m.skills, *m.commands,
                    *m.rules, *m.mcp_servers,
                ):
                    installed_names.add(n.removesuffix(".md"))
            except RuntimeError:
                pass

        sections = {
            "Agents": agents,
            "Skills": skills,
            "Commands": commands,
            "Rules": rules,
            "MCP Servers": mcp_servers,
        }
        display.print("Available artifacts:", style="info")

    total = 0
    for label, items in sections.items():
        if not items:
            continue
        display.print(f"\n  {label}:")
        for name in items:
            shown = _display_name(name)
            marker = ""
            if not args.installed and shown in installed_names:
                marker = " (installed)"
            display.print(f"    - {shown}{marker}")
            total += 1

    if total == 0:
        display.print("  (none)", style="dim")

    return 0


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    if args.command is None:
        args.command = "apply"
        if not hasattr(args, "plain"):
            args.plain = False

    config_root = get_config_root()
    log_path = config_root / LOG_FILENAME
    display = PlainDisplay() if getattr(args, "plain", False) else RichDisplay()

    try:
        if args.command == "install":
            return _run_install(args, display)
        if args.command == "import":
            return _run_import(args, display)
        if args.command == "plan":
            return _run_plan(args, config_root, display)
        if args.command == "init":
            return _run_init(args, config_root, display)
        if args.command == "doctor":
            return _run_doctor(config_root, display)
        if args.command == "uninstall":
            return _run_uninstall(args, display)
        if args.command == "apply":
            return _run_apply(args, config_root, display)
    except Exception as exc:
        handle_fatal(exc, display, log_path)
        return 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
