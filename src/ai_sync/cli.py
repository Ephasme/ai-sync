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
from typing import Iterator, cast

import yaml

from .config_store import DEFAULT_SECRET_PROVIDER, ensure_layout, get_config_root, load_config, write_config
from .repo_store import (
    SLUG_ERROR_MSG,
    SLUG_RE,
    RepoEntry,
    _dest_for_name,
    copy_repo_to_store,
    get_all_repo_roots,
    get_repo_root,
    load_repos,
    save_repos,
    validate_slug,
)
from .display import PlainDisplay, RichDisplay
from .display.base import Display
from .env_loader import collect_env_refs, resolve_env_refs_in_obj
from .error_handler import LOG_FILENAME, handle_fatal
from .gitignore import SENSITIVE_PATHS, check_gitignore, write_gitignore_entries
from .interactive import run_init_prompts
from .manifest_loader import load_and_filter_mcp
from .op_inject import load_runtime_env_from_op
from .project import (
    find_project_root,
    load_defaults,
    resolve_project_manifest,
    validate_against_registry,
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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sync AI configs (agents, skills, commands, MCP servers) per-project."
    )
    subparsers = parser.add_subparsers(dest="command")

    install_parser = subparsers.add_parser("install", help="Initialize ~/.ai-sync and store 1Password settings.")
    install_parser.add_argument("--op-account", metavar="NAME", help="1Password account name (desktop app auth).")
    install_parser.add_argument("--force", action="store_true", help="Overwrite existing config.toml.")

    import_parser = subparsers.add_parser("import", help="Import config from a repo into ~/.ai-sync.")
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

    init_parser = subparsers.add_parser("init", help="Initialize .ai-sync.yaml in the current project.")
    init_parser.add_argument(
        "--tag",
        metavar="TAG[,TAG...]",
        help="Comma-separated tags; auto-selects matching artifacts and skips interactive prompts.",
    )

    apply_parser = subparsers.add_parser("apply", help="Apply ai-sync config to the current project.")
    apply_parser.add_argument("--plain", action="store_true", help="Plain output mode (no interactive prompts).")

    subparsers.add_parser("doctor", help="Check setup and project health.")

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


def _discover_registry(repo_roots: list[Path]) -> tuple[list[str], list[str], list[str], list[str]]:
    agents_seen: dict[str, str] = {}
    skills_seen: dict[str, str] = {}
    commands_seen: dict[str, str] = {}
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
                if cmd_path.is_file():
                    rel = cmd_path.relative_to(commands_dir).as_posix()
                    commands_seen[rel] = rel

        mcp_path = repo_root / "mcp-servers.yaml"
        if mcp_path.exists():
            with open(mcp_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            for server_id in (data.get("servers") or {}).keys():
                mcp_servers_seen[server_id] = server_id

    return (
        sorted(agents_seen),
        sorted(skills_seen),
        sorted(commands_seen),
        sorted(mcp_servers_seen),
    )


def _discover_artifact_tags(repo_roots: list[Path]) -> dict[str, dict[str, list[str]]]:
    """Return tags for every artifact, keyed by artifact name/path. Last repo wins per artifact."""
    result: dict[str, dict[str, list[str]]] = {
        "agents": {},
        "skills": {},
        "commands": {},
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

        mcp_path = repo_root / "mcp-servers.yaml"
        if mcp_path.exists():
            with open(mcp_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            for server_id, server_cfg in (data.get("servers") or {}).items():
                if isinstance(server_cfg, dict):
                    tags = server_cfg.get("tags") or []
                    if isinstance(tags, list) and tags:
                        result["mcp-servers"][server_id] = tags

    return result


def _filter_by_tags(artifacts: list[str], artifact_tags: dict[str, list[str]], tags: set[str]) -> list[str]:
    """Return artifacts that have at least one of the given tags (OR logic)."""
    return [a for a in artifacts if tags & set(artifact_tags.get(a) or [])]


def _run_init(args: argparse.Namespace, config_root: Path, display: Display) -> int:
    if not config_root.exists() or not (config_root / "config.toml").exists():
        display.panel(
            "Run `ai-sync install` and `ai-sync import` first.",
            title="Not set up",
            style="error",
        )
        return 1

    repo_roots = get_all_repo_roots(config_root)
    if not repo_roots:
        display.panel(
            "No repos imported. Run `ai-sync import` first.",
            title="No repos",
            style="error",
        )
        return 1

    project_root = Path.cwd()
    if (project_root / ".ai-sync.yaml").exists():
        display.panel(
            f".ai-sync.yaml already exists in {project_root}.",
            title="Already initialised",
            style="error",
        )
        return 1

    agents, skills, commands, mcp_servers = _discover_registry(repo_roots)
    defaults = load_defaults(repo_roots)

    tag_arg: str | None = getattr(args, "tag", None)
    if tag_arg:
        tags = {t.strip() for t in tag_arg.split(",") if t.strip()}
        artifact_tags = _discover_artifact_tags(repo_roots)
        selected_agents = _filter_by_tags(agents, artifact_tags["agents"], tags)
        selected_skills = _filter_by_tags(skills, artifact_tags["skills"], tags)
        selected_commands = _filter_by_tags(commands, artifact_tags["commands"], tags)
        selected_mcp = _filter_by_tags(mcp_servers, artifact_tags["mcp-servers"], tags)
        default_settings = defaults.get("settings") or {}
        tools_defaults = default_settings.get("tools") or {}
        result = {
            "agents": selected_agents,
            "skills": selected_skills,
            "commands": selected_commands,
            "mcp-servers": selected_mcp,
            "settings": {
                "mode": default_settings.get("mode", "normal"),
                "experimental": default_settings.get("experimental", True),
                "subagents": default_settings.get("subagents", True),
                "tools": {"sandbox": tools_defaults.get("sandbox", False)},
            },
        }
        display.print(
            f"Auto-selected {len(selected_agents)} agents, {len(selected_skills)} skills, "
            f"{len(selected_commands)} commands, {len(selected_mcp)} MCP servers "
            f"matching tags: {', '.join(sorted(tags))}",
            style="success",
        )
    else:
        result = run_init_prompts(display, agents, skills, commands, mcp_servers, defaults)
        if result is None:
            display.print("Cancelled.", style="dim")
            return 1

    ai_sync_yaml = project_root / ".ai-sync.yaml"
    with open(ai_sync_yaml, "w", encoding="utf-8") as f:
        yaml.safe_dump(result, f, sort_keys=False, default_flow_style=False)
    display.print(f"Wrote {ai_sync_yaml}", style="success")

    ai_sync_dir = project_root / ".ai-sync"
    ai_sync_dir.mkdir(parents=True, exist_ok=True)

    write_gitignore_entries(project_root, SENSITIVE_PATHS)
    display.print("Updated .gitignore with ai-sync entries", style="success")

    return 0


def _run_apply(args: argparse.Namespace, config_root: Path, display: Display) -> int:
    if not config_root.exists() or not (config_root / "config.toml").exists():
        display.panel(
            "Run `ai-sync install` first.",
            title="Not set up",
            style="error",
        )
        return 1

    repo_roots = get_all_repo_roots(config_root)
    if not repo_roots:
        display.panel(
            "No repos imported. Run `ai-sync import` first.",
            title="No repos",
            style="error",
        )
        return 1

    project_root = find_project_root()
    if project_root is None:
        display.panel(
            "No .ai-sync.yaml found. Run `ai-sync init` to set up this project.",
            title="No project",
            style="error",
        )
        return 1

    manifest = resolve_project_manifest(project_root)

    warnings = validate_against_registry(manifest, repo_roots)
    for w in warnings:
        display.print(f"Warning: {w}", style="warning")

    uncovered = check_gitignore(project_root)
    if uncovered and manifest.mcp_servers:
        display.panel(
            "The following sensitive paths are not covered by .gitignore:\n"
            + "\n".join(f"  - {p}" for p in uncovered)
            + "\n\nRun `ai-sync init` or add them manually to .gitignore.",
            title="Gitignore gate failed",
            style="error",
        )
        return 1

    versions_path = get_default_versions_path()
    ok, msg = check_client_versions(versions_path)
    if not ok:
        display.print(f"Warning: {msg}", style="warning")
    elif msg != "OK":
        display.print(f"Warning: {msg}", style="warning")

    mcp_manifest = load_and_filter_mcp(repo_roots, manifest.mcp_servers, display)

    required_vars = collect_env_refs(mcp_manifest)
    secrets: dict = {"servers": {}}
    if required_vars:
        runtime_env: dict[str, str] = {}
        for repo_root in repo_roots:
            tpl = repo_root / ".env.tpl"
            if tpl.exists():
                runtime_env.update(load_runtime_env_from_op(tpl, config_root))
        missing = sorted(required_vars - runtime_env.keys())
        if missing:
            display.panel(
                f"MCP config references env vars not defined in any .env.tpl: {', '.join(missing)}",
                title="Missing env vars",
                style="error",
            )
            return 1
        mcp_manifest = cast(dict, resolve_env_refs_in_obj(mcp_manifest, runtime_env))

    return run_apply(
        project_root=project_root,
        repo_roots=repo_roots,
        manifest=manifest,
        mcp_manifest=mcp_manifest,
        secrets=secrets,
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
            display.print(
                f"  .ai-sync.yaml: OK ({len(manifest.agents)} agents, "
                f"{len(manifest.skills)} skills, {len(manifest.mcp_servers)} MCP servers)",
                style="success",
            )
        except RuntimeError as exc:
            display.print(f"  .ai-sync.yaml: {exc}", style="warning")
            return 1

        repo_roots = get_all_repo_roots(config_root)
        warnings = validate_against_registry(manifest, repo_roots)
        for w in warnings:
            display.print(f"  Warning: {w}", style="warning")

        uncovered = check_gitignore(project_root)
        if uncovered:
            display.print(f"  Gitignore: MISSING coverage for {', '.join(uncovered)}", style="warning")
        else:
            display.print("  Gitignore: OK", style="success")
    else:
        display.print("\nNo project found (no .ai-sync.yaml in current directory tree)", style="dim")

    return 0


def _run_uninstall(args: argparse.Namespace, display: Display) -> int:
    project_root = find_project_root()
    if project_root is None:
        display.panel("No .ai-sync.yaml found. Nothing to uninstall.", title="No project", style="error")
        return 1
    return run_uninstall(project_root, apply=bool(args.apply))


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
