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
from .display import PlainDisplay, RichDisplay
from .env_loader import collect_env_refs, resolve_env_refs_in_obj
from .gitignore import SENSITIVE_PATHS, check_gitignore, write_gitignore_entries
from .manifest_loader import load_and_filter_mcp
from .op_inject import load_runtime_env_from_op
from .project import (
    ProjectManifest,
    find_project_root,
    load_defaults,
    resolve_project_manifest,
    validate_against_registry,
)
from .sync_runner import run_apply
from .uninstall import run_uninstall
from .version_checks import check_client_versions, get_default_versions_path


@contextmanager
def _resolve_repo_source(repo: str) -> Iterator[Path]:
    repo_path = Path(repo).expanduser()
    if repo_path.exists():
        yield repo_path
        return
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

    subparsers.add_parser("init", help="Initialize .ai-sync.yaml in the current project.")

    apply_parser = subparsers.add_parser("apply", help="Apply ai-sync config to the current project.")
    apply_parser.add_argument("--plain", action="store_true", help="Plain output mode (no interactive prompts).")

    subparsers.add_parser("doctor", help="Check setup and project health.")

    uninstall_parser = subparsers.add_parser("uninstall", help="Remove ai-sync managed changes from current project.")
    uninstall_parser.add_argument("--apply", action="store_true", help="Apply uninstall (default is dry-run).")

    return parser


def _run_install(args: argparse.Namespace) -> int:
    root = ensure_layout()
    config_path = root / "config.toml"
    if config_path.exists() and not args.force:
        print(f"Config already exists: {config_path}. Use --force to overwrite.", file=sys.stderr)
        return 1

    op_account = args.op_account or os.environ.get("OP_ACCOUNT")
    token = os.environ.get("OP_SERVICE_ACCOUNT_TOKEN")
    if not op_account and not token:
        if sys.stdin.isatty():
            op_account = input("1Password account name (as shown in app): ").strip() or None
        if not op_account:
            print(
                "Missing OP account. Provide --op-account NAME, set OP_ACCOUNT, or set OP_SERVICE_ACCOUNT_TOKEN.",
                file=sys.stderr,
            )
            return 1

    config = {"secret_provider": DEFAULT_SECRET_PROVIDER}
    if op_account:
        config["op_account"] = op_account
    write_config(config, root)
    print(f"Wrote {config_path}")
    return 0


def _copy_dir_if_exists(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def _copy_file_if_exists(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _run_import(args: argparse.Namespace) -> int:
    root = ensure_layout()
    config_path = root / "config.toml"
    with _resolve_repo_source(args.repo) as repo_root:
        dest_config = root / "config"
        _copy_dir_if_exists(repo_root / "prompts", dest_config / "prompts")
        _copy_dir_if_exists(repo_root / "skills", dest_config / "skills")
        _copy_dir_if_exists(repo_root / "commands", dest_config / "commands")
        _copy_file_if_exists(repo_root / "mcp-servers.yaml", dest_config / "mcp-servers.yaml")
        _copy_file_if_exists(repo_root / "defaults.yaml", dest_config / "defaults.yaml")
        _copy_file_if_exists(repo_root / ".env.tpl", root / ".env.tpl")
    if not config_path.exists():
        print("Warning: ~/.ai-sync/config.toml is missing. Run `ai-sync install`.", file=sys.stderr)
    print(f"Imported config from {args.repo} to {root}")
    return 0


def _discover_registry(config_root: Path) -> tuple[list[str], list[str], list[str], list[str]]:
    prompts_dir = config_root / "config" / "prompts"
    agents = sorted(p.stem for p in prompts_dir.glob("*.md")) if prompts_dir.exists() else []

    skills_dir = config_root / "config" / "skills"
    skills = sorted(
        d.name for d in skills_dir.iterdir() if d.is_dir() and (d / "SKILL.md").exists()
    ) if skills_dir.exists() else []

    commands_dir = config_root / "config" / "commands"
    commands: list[str] = []
    if commands_dir.exists():
        for cmd_path in sorted(commands_dir.rglob("*")):
            if cmd_path.is_file():
                commands.append(cmd_path.relative_to(commands_dir).as_posix())

    mcp_path = config_root / "config" / "mcp-servers.yaml"
    mcp_servers: list[str] = []
    if mcp_path.exists():
        try:
            with open(mcp_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            mcp_servers = sorted((data.get("servers") or {}).keys())
        except (yaml.YAMLError, OSError):
            pass

    return agents, skills, commands, mcp_servers


def _run_init(config_root: Path) -> int:
    if not config_root.exists() or not (config_root / "config.toml").exists():
        print("Missing ~/.ai-sync/. Run `ai-sync install` and `ai-sync import` first.", file=sys.stderr)
        return 1

    project_root = Path.cwd()
    if (project_root / ".ai-sync.yaml").exists():
        print(f".ai-sync.yaml already exists in {project_root}.", file=sys.stderr)
        return 1

    agents, skills, commands, mcp_servers = _discover_registry(config_root)
    defaults = load_defaults(config_root)

    from .display import RichDisplay
    from .interactive import run_init_prompts

    display = RichDisplay()
    result = run_init_prompts(display, agents, skills, commands, mcp_servers, defaults)
    if result is None:
        print("Cancelled.", file=sys.stderr)
        return 1

    ai_sync_yaml = project_root / ".ai-sync.yaml"
    with open(ai_sync_yaml, "w", encoding="utf-8") as f:
        yaml.safe_dump(result, f, sort_keys=False, default_flow_style=False)
    print(f"Wrote {ai_sync_yaml}")

    ai_sync_dir = project_root / ".ai-sync"
    ai_sync_dir.mkdir(parents=True, exist_ok=True)

    write_gitignore_entries(project_root, SENSITIVE_PATHS)
    print("Updated .gitignore with ai-sync entries")

    return 0


def _run_apply(args: argparse.Namespace, config_root: Path) -> int:
    if not config_root.exists() or not (config_root / "config.toml").exists():
        print("Missing ~/.ai-sync/config.toml. Run `ai-sync install` first.", file=sys.stderr)
        return 1

    project_root = find_project_root()
    if project_root is None:
        if sys.stdin.isatty() and not args.plain:
            print("No .ai-sync.yaml found. Run `ai-sync init` to set up this project.", file=sys.stderr)
        else:
            print("No .ai-sync.yaml found.", file=sys.stderr)
        return 1

    display = PlainDisplay() if args.plain else RichDisplay()

    manifest = resolve_project_manifest(project_root)

    warnings = validate_against_registry(manifest, config_root)
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

    mcp_manifest = load_and_filter_mcp(config_root, manifest.mcp_servers, display)

    env_tpl = config_root / ".env.tpl"
    required_vars = collect_env_refs(mcp_manifest)
    secrets: dict = {"servers": {}}
    if required_vars:
        if not env_tpl.exists():
            names = ", ".join(sorted(required_vars))
            raise RuntimeError(
                f"MCP config references env vars ({names}) but {env_tpl} is missing. "
                "Create the file with the required variables (use op:// refs for 1Password secrets)."
            )
        runtime_env = load_runtime_env_from_op(env_tpl, config_root)
        missing = sorted(required_vars - runtime_env.keys())
        if missing:
            raise RuntimeError(
                f"MCP config references env vars not defined in .env.tpl: {', '.join(missing)}"
            )
        mcp_manifest = cast(dict, resolve_env_refs_in_obj(mcp_manifest, runtime_env))

    try:
        return run_apply(
            project_root=project_root,
            config_root=config_root,
            manifest=manifest,
            mcp_manifest=mcp_manifest,
            secrets=secrets,
            display=display,
        )
    except Exception as exc:
        try:
            display.panel(str(exc), title="Apply failed", style="error")
        except Exception:
            pass
        print(f"Apply failed: {exc}", file=sys.stderr)
        return 1


def _run_doctor(config_root: Path) -> int:
    print(f"Config root: {config_root}")
    if not config_root.exists():
        print("  Missing config root. Run `ai-sync install`.")
        return 1
    config_path = config_root / "config.toml"
    if not config_path.exists():
        print("  Missing config.toml. Run `ai-sync install`.")
        return 1

    try:
        config = load_config(config_root)
    except RuntimeError as exc:
        print(f"  Failed to read config: {exc}")
        return 1

    op_account = os.environ.get("OP_ACCOUNT") or config.get("op_account")
    token = os.environ.get("OP_SERVICE_ACCOUNT_TOKEN")
    if token:
        print("  1Password auth: OK (service account token)")
    elif op_account:
        print(f"  1Password auth: OK (OP_ACCOUNT={op_account})")
    else:
        print("  1Password auth: missing (set OP_SERVICE_ACCOUNT_TOKEN or OP_ACCOUNT)")
        return 1

    required_paths = [
        config_root / "config" / "prompts",
        config_root / "config" / "skills",
        config_root / "config" / "mcp-servers.yaml",
        config_root / "config" / "defaults.yaml",
    ]
    for path in required_paths:
        status = "OK" if path.exists() else "missing"
        print(f"  {path}: {status}")

    project_root = find_project_root()
    if project_root:
        print(f"\nProject: {project_root}")
        try:
            manifest = resolve_project_manifest(project_root)
            print(f"  .ai-sync.yaml: OK ({len(manifest.agents)} agents, {len(manifest.skills)} skills, {len(manifest.mcp_servers)} MCP servers)")
        except RuntimeError as exc:
            print(f"  .ai-sync.yaml: {exc}")
            return 1

        warnings = validate_against_registry(manifest, config_root)
        for w in warnings:
            print(f"  Warning: {w}")

        uncovered = check_gitignore(project_root)
        if uncovered:
            print(f"  Gitignore: MISSING coverage for {', '.join(uncovered)}")
        else:
            print("  Gitignore: OK")
    else:
        print("\nNo project found (no .ai-sync.yaml in current directory tree)")

    return 0


def _run_uninstall(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    if project_root is None:
        print("No .ai-sync.yaml found. Nothing to uninstall.", file=sys.stderr)
        return 1
    try:
        return run_uninstall(project_root, apply=bool(args.apply))
    except Exception as exc:
        print(f"Uninstall failed: {exc}", file=sys.stderr)
        return 1


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    if args.command is None:
        args.command = "apply"
        if not hasattr(args, "plain"):
            args.plain = False

    config_root = get_config_root()

    if args.command == "install":
        return _run_install(args)
    if args.command == "import":
        return _run_import(args)
    if args.command == "init":
        return _run_init(config_root)
    if args.command == "doctor":
        return _run_doctor(config_root)
    if args.command == "uninstall":
        return _run_uninstall(args)
    if args.command == "apply":
        return _run_apply(args, config_root)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
