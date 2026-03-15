"""CLI entrypoint."""

from __future__ import annotations

import argparse
import sys
import webbrowser
from collections.abc import Callable
from pathlib import Path

from .di import bootstrap_runtime
from .services.error_handler_service import LOG_FILENAME
from .services.plain_display_service import PlainDisplayService
from .services.rich_display_service import RichDisplayService


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sync AI configs (agents, skills, commands, rules, MCP servers) per-project.",
    )
    subparsers = parser.add_subparsers(dest="command")

    install_parser = subparsers.add_parser(
        "install", help="Initialize ~/.ai-sync bootstrap and store auth settings."
    )
    install_parser.add_argument(
        "--op-account-identifier",
        metavar="SIGNIN_ADDRESS_OR_USER_ID",
        help="1Password sign-in address or user ID for desktop app auth (example: example.1password.com).",
    )
    install_parser.add_argument(
        "--force", action="store_true", help="Overwrite existing config.toml."
    )

    plan_parser = subparsers.add_parser(
        "plan", help="Resolve sources, render a plan, and save a plan artifact."
    )
    plan_parser.add_argument(
        "--plain", action="store_true", help="Plain output mode (no interactive prompts)."
    )
    plan_parser.add_argument("--out", metavar="PATH", help="Write the plan artifact to PATH.")

    apply_parser = subparsers.add_parser(
        "apply", help="Apply ai-sync config to the current project."
    )
    apply_parser.add_argument(
        "--plain", action="store_true", help="Plain output mode (no interactive prompts)."
    )
    apply_parser.add_argument(
        "planfile", nargs="?", help="Optional saved plan file to validate and apply."
    )

    subparsers.add_parser("doctor", help="Check machine bootstrap and project planning health.")

    uninstall_parser = subparsers.add_parser(
        "uninstall", help="Remove ai-sync managed changes from current project."
    )
    uninstall_parser.add_argument(
        "--apply", action="store_true", help="Apply uninstall (default is dry-run)."
    )

    ui_parser = subparsers.add_parser("ui", help="Start the ai-sync local web UI.")
    ui_parser.add_argument("--host", default="127.0.0.1", help="Host to bind the UI server to.")
    ui_parser.add_argument("--port", type=int, default=8321, help="Port to bind the UI server to.")

    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    if args.command is None:
        args.command = "apply"
        if not hasattr(args, "plain"):
            args.plain = False

    runtime = bootstrap_runtime()
    config_root = runtime.container.config_store_service().get_config_root()
    log_path = config_root / LOG_FILENAME
    display = (
        PlainDisplayService()
        if getattr(args, "plain", False)
        else RichDisplayService()
    )

    try:
        if args.command == "install":
            return runtime.install_service.run(
                display=display,
                op_account_identifier=args.op_account_identifier,
                force=bool(args.force),
            )
        if args.command == "plan":
            return runtime.plan_service.run(
                config_root=config_root, display=display, out=args.out
            )
        if args.command == "doctor":
            return runtime.doctor_service.run(config_root=config_root, display=display)
        if args.command == "uninstall":
            return runtime.uninstall_service.run(display=display, apply=bool(args.apply))
        if args.command == "apply":
            return runtime.apply_service.run(
                config_root=config_root, display=display, planfile=args.planfile
            )
        if args.command == "ui":
            return _run_ui(runtime=runtime, config_root=config_root, host=args.host, port=args.port)
    except Exception as exc:
        runtime.error_handler_service.handle_fatal(exc, display, log_path)
        return 1

    parser.print_help()
    return 1

def _run_ui(
    *,
    runtime,
    config_root: Path,
    host: str,
    port: int,
    open_browser=webbrowser.open,
    run_server: Callable[..., None] | None = None,
) -> int:
    config_path = config_root / "config.toml"
    if not config_path.exists():
        raise RuntimeError("Run `ai-sync install` first.")

    project_root = runtime.container.project_locator_service().find_project_root()
    workspace_root = Path.cwd().resolve()

    try:
        import uvicorn

        from .web import create_app
    except ImportError as exc:
        raise RuntimeError(
            "The web UI dependencies are not installed in the current ai-sync environment. "
            "If you are working from this repository, run `poetry run ai-sync ui` or "
            "`.venv/bin/ai-sync ui`. If you installed `ai-sync` via pipx or another global "
            "environment, reinstall or upgrade that environment so it includes the new web UI "
            "dependencies."
        ) from exc

    app = create_app(
        container=runtime.container,
        project_root=project_root,
        config_root=config_root,
        workspace_root=workspace_root,
    )
    open_browser(_browser_url(host, port))
    server_runner = uvicorn.run if run_server is None else run_server
    server_runner(app, host=host, port=port)
    return 0


def _browser_url(host: str, port: int) -> str:
    browser_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    return f"http://{browser_host}:{port}"


if __name__ == "__main__":
    sys.exit(main())
