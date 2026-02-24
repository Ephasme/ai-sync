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

from .config_store import DEFAULT_SECRET_PROVIDER, ensure_layout, get_config_root, load_config, write_config
from .display import PlainDisplay, RichDisplay
from .precedence import parse_override
from .sync_runner import run_sync
from .uninstall import run_uninstall


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
        description="Sync AI configs (agents, skills, MCP servers) to Codex, Cursor, Gemini."
    )
    subparsers = parser.add_subparsers(dest="command")

    setup_parser = subparsers.add_parser("setup", help="Initialize ~/.ai-sync and store 1Password settings.")
    setup_parser.add_argument("--op-account", metavar="NAME", help="1Password account name (desktop app auth).")
    setup_parser.add_argument("--force", action="store_true", help="Overwrite existing config.toml.")

    import_parser = subparsers.add_parser("import", help="Import config from a repo into ~/.ai-sync.")
    import_parser.add_argument("--repo", required=True, help="Local path or git URL to import from.")

    sync_parser = subparsers.add_parser("sync", help="Run sync using ~/.ai-sync as source.")
    sync_parser.add_argument("--force", action="store_true", help="Update version lock then sync.")
    sync_parser.add_argument("--no-interactive", action="store_true", help="Skip interactive prompts.")
    sync_parser.add_argument("--plain", action="store_true", help="Plain output mode. Implies --no-interactive.")
    sync_parser.add_argument("--override", action="append", default=[], help="Override leaf value: /path/to/key=value")
    sync_parser.add_argument(
        "--override-json",
        action="append",
        default=[],
        help="Override leaf value with JSON: /path/to/key=<json>",
    )

    subparsers.add_parser("doctor", help="Check setup and 1Password auth configuration.")
    uninstall_parser = subparsers.add_parser("uninstall", help="Remove ai-sync managed changes.")
    uninstall_parser.add_argument("--apply", action="store_true", help="Apply uninstall (default is dry-run).")

    return parser


def _run_setup(args: argparse.Namespace) -> int:
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


def _copy_dir(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def _copy_dir_if_exists(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    _copy_dir(src, dst)


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
        _copy_dir_if_exists(repo_root / "rules", dest_config / "rules")
        _copy_file_if_exists(repo_root / "mcp-servers.yaml", dest_config / "mcp-servers" / "servers.yaml")
        _copy_file_if_exists(
            repo_root / "client-settings.yaml",
            dest_config / "client-settings" / "settings.yaml",
        )
        _copy_file_if_exists(repo_root / ".env.tpl", root / ".env.tpl")
    if not config_path.exists():
        print("Warning: ~/.ai-sync/config.toml is missing. Run `ai-sync setup`.", file=sys.stderr)
    print(f"Imported config from {args.repo} to {root}")
    return 0


def _run_sync(args: argparse.Namespace) -> int:
    config_root = get_config_root()
    config_path = config_root / "config.toml"
    if not config_root.exists() or not config_path.exists():
        print("Missing ~/.ai-sync/config.toml. Run `ai-sync setup` first.", file=sys.stderr)
        return 1

    display = PlainDisplay() if args.plain else RichDisplay()
    overrides: list[tuple[str, object]] = []
    try:
        for item in args.override:
            overrides.append(parse_override(item, parse_json=False))
        for item in args.override_json:
            overrides.append(parse_override(item, parse_json=True))
    except RuntimeError as exc:
        print(f"Sync failed: {exc}", file=sys.stderr)
        return 1

    try:
        return run_sync(
            config_root=config_root,
            force=args.force,
            no_interactive=(args.no_interactive or args.plain),
            plain=args.plain,
            overrides=overrides,
            display=display,
        )
    except Exception as exc:
        try:
            display.panel(str(exc), title="Sync failed", style="error")
        except Exception:
            pass
        print(f"Sync failed: {exc}", file=sys.stderr)
        return 1


def _run_doctor() -> int:
    root = get_config_root()
    config_path = root / "config.toml"
    print(f"Config root: {root}")
    if not root.exists():
        print("  Missing config root. Run `ai-sync setup`.")
        return 1
    if not config_path.exists():
        print("  Missing config.toml. Run `ai-sync setup`.")
        return 1

    try:
        config = load_config(root)
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

    required_dirs = [
        root / "config" / "prompts",
        root / "config" / "skills",
        root / "config" / "mcp-servers",
        root / "config" / "client-settings",
    ]
    for path in required_dirs:
        status = "OK" if path.exists() else "missing"
        print(f"  {path}: {status}")
    return 0


def _run_uninstall(args: argparse.Namespace) -> int:
    try:
        return run_uninstall(apply=bool(args.apply))
    except Exception as exc:
        print(f"Uninstall failed: {exc}", file=sys.stderr)
        return 1


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    if args.command is None:
        args.command = "sync"

    if args.command == "setup":
        return _run_setup(args)
    if args.command == "import":
        return _run_import(args)
    if args.command == "doctor":
        return _run_doctor()
    if args.command == "uninstall":
        return _run_uninstall(args)
    if args.command == "sync":
        return _run_sync(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
