"""CLI entrypoint."""

from __future__ import annotations

import argparse
import sys

from .command_handlers import (
    run_apply_command,
    run_doctor_command,
    run_install_command,
    run_plan_command,
    run_uninstall_command,
)
from .config_store import get_config_root
from .display import PlainDisplay, RichDisplay
from .error_handler import LOG_FILENAME, handle_fatal


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sync AI configs (agents, skills, commands, rules, MCP servers) per-project.",
    )
    subparsers = parser.add_subparsers(dest="command")

    install_parser = subparsers.add_parser("install", help="Initialize ~/.ai-sync bootstrap and store auth settings.")
    install_parser.add_argument(
        "--op-account-identifier",
        metavar="SIGNIN_ADDRESS_OR_USER_ID",
        help="1Password sign-in address or user ID for desktop app auth (example: example.1password.com).",
    )
    install_parser.add_argument("--force", action="store_true", help="Overwrite existing config.toml.")

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
            return run_install_command(
                display=display,
                op_account_identifier=args.op_account_identifier,
                force=bool(args.force),
            )
        if args.command == "plan":
            return run_plan_command(config_root=config_root, display=display, out=args.out)
        if args.command == "doctor":
            return run_doctor_command(config_root=config_root, display=display)
        if args.command == "uninstall":
            return run_uninstall_command(display=display, apply=bool(args.apply))
        if args.command == "apply":
            return run_apply_command(config_root=config_root, display=display, planfile=args.planfile)
    except Exception as exc:
        handle_fatal(exc, display, log_path)
        return 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
