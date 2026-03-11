"""Top-level command handlers used by the CLI entrypoint."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, TextIO

from .config_store import DEFAULT_SECRET_PROVIDER, ensure_layout, load_config, write_config
from .display.base import Display
from .gitignore import check_gitignore
from .planning import (
    PlanContext,
    build_plan_context,
    default_plan_path,
    render_plan,
    save_plan,
    validate_saved_plan,
)
from .project import find_project_root, resolve_project_manifest, resolve_project_manifest_path
from .sync_runner import run_apply
from .uninstall import run_uninstall
from .version_checks import check_client_versions, get_default_versions_path


@dataclass(frozen=True)
class PreparedProjectContext:
    project_root: Path
    plan_context: PlanContext


def run_install_command(
    *,
    display: Display,
    op_account_identifier: str | None,
    force: bool,
    environ: Mapping[str, str] | None = None,
    stdin: TextIO | None = None,
    prompt_input: Callable[[str], str] = input,
) -> int:
    root = ensure_layout()
    config_path = root / "config.toml"
    if config_path.exists() and not force:
        display.panel(
            f"Config already exists: {config_path}\nUse --force to overwrite.",
            title="Already installed",
            style="error",
        )
        return 1

    runtime_env = os.environ if environ is None else environ
    current_stdin = sys.stdin if stdin is None else stdin
    resolved_op_account_identifier = op_account_identifier or runtime_env.get("OP_ACCOUNT")
    token = runtime_env.get("OP_SERVICE_ACCOUNT_TOKEN")

    if not resolved_op_account_identifier and not token:
        if current_stdin.isatty():
            resolved_op_account_identifier = (
                prompt_input(
                    "1Password sign-in address or user ID "
                    "(example: example.1password.com): "
                ).strip()
                or None
            )
        if not resolved_op_account_identifier:
            display.panel(
                "No 1Password account configured.\n"
                "Provide --op-account-identifier with a sign-in address or user ID "
                "(example: example.1password.com), set OP_ACCOUNT, "
                "or set OP_SERVICE_ACCOUNT_TOKEN.",
                title="Missing account",
                style="error",
            )
            return 1

    config = {"secret_provider": DEFAULT_SECRET_PROVIDER}
    if resolved_op_account_identifier:
        config["op_account_identifier"] = resolved_op_account_identifier
    write_config(config, root)
    display.print(f"Wrote {config_path}", style="success")
    return 0


def run_plan_command(*, config_root: Path, display: Display, out: str | None) -> int:
    prepared = _prepare_project_context(config_root=config_root, display=display)
    if prepared is None:
        return 1

    render_plan(prepared.plan_context.plan, display)
    out_path = Path(out).expanduser() if out else default_plan_path(prepared.project_root)
    save_plan(prepared.plan_context.plan, out_path)
    display.print(f"Saved plan to {out_path}", style="success")
    return 0


def run_apply_command(*, config_root: Path, display: Display, planfile: str | None) -> int:
    prepared = _prepare_project_context(config_root=config_root, display=display)
    if prepared is None:
        return 1

    if planfile:
        plan_to_apply = validate_saved_plan(Path(planfile).expanduser(), prepared.plan_context.plan)
        display.print(f"Validated saved plan: {planfile}", style="success")
    else:
        plan_to_apply = prepared.plan_context.plan
        display.print("Applying a fresh plan computed from the current project state.", style="info")

    render_plan(plan_to_apply, display)
    if not _confirm_plan_deletions(plan_to_apply, display):
        return 1

    return run_apply(
        project_root=prepared.project_root,
        source_roots={alias: source.root for alias, source in prepared.plan_context.resolved_sources.items()},
        manifest=prepared.plan_context.manifest,
        mcp_manifest=prepared.plan_context.mcp_manifest,
        secrets=prepared.plan_context.secrets,
        runtime_env=prepared.plan_context.runtime_env,
        display=display,
    )


def _confirm_plan_deletions(
    plan,
    display: Display,
    *,
    stdin: TextIO | None = None,
    prompt_input: Callable[[str], str] = input,
) -> bool:
    delete_actions = [action for action in plan.actions if action.action == "delete"]
    if not delete_actions:
        return True

    display.print(
        f"Warning: plan includes {len(delete_actions)} deletion(s). Review before applying.",
        style="warning",
    )
    for action in delete_actions:
        display.print(
            f"  - {action.kind}: {action.resource} -> {action.target}",
            style="warning",
        )

    current_stdin = sys.stdin if stdin is None else stdin
    if not current_stdin.isatty():
        display.panel(
            "Refusing to apply deletions in non-interactive mode.\n"
            "Run interactively and confirm, or update the plan to remove deletions.",
            title="Deletion confirmation required",
            style="error",
        )
        return False

    answer = prompt_input("Continue with these deletions? [y/N]: ").strip().lower()
    if answer not in {"y", "yes"}:
        display.print("Apply cancelled by user.", style="warning")
        return False
    return True


def run_doctor_command(*, config_root: Path, display: Display) -> int:
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

    op_account_identifier = os.environ.get("OP_ACCOUNT") or config.get("op_account_identifier")
    token = os.environ.get("OP_SERVICE_ACCOUNT_TOKEN")
    if token:
        display.print("  1Password auth: OK (service account token)", style="success")
    elif op_account_identifier:
        display.print(f"  1Password auth: OK (OP_ACCOUNT={op_account_identifier})", style="success")
    else:
        display.print(
            "  1Password auth: missing (set OP_SERVICE_ACCOUNT_TOKEN or OP_ACCOUNT to a sign-in address or user ID)",
            style="warning",
        )
        return 1

    project_root = find_project_root()
    if project_root is None:
        display.print(
            "\nNo project found (no .ai-sync.local.yaml or .ai-sync.yaml in current directory tree)",
            style="dim",
        )
        return 0

    display.print(f"\nProject: {project_root}")
    try:
        manifest_path = resolve_project_manifest_path(project_root)
        manifest = resolve_project_manifest(project_root)
        display.print(f"  {manifest_path.name}: OK ({len(manifest.sources)} sources declared)", style="success")
    except RuntimeError as exc:
        display.print(f"  project manifest: {exc}", style="warning")
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

    return 0


def run_uninstall_command(*, display: Display, apply: bool) -> int:
    project_root = find_project_root()
    if project_root is None:
        display.panel(
            "No .ai-sync.local.yaml or .ai-sync.yaml found. Nothing to uninstall.",
            title="No project",
            style="error",
        )
        return 1
    return run_uninstall(project_root, apply=apply)


def _prepare_project_context(
    *,
    config_root: Path,
    display: Display,
) -> PreparedProjectContext | None:
    if not _ensure_installed(config_root, display):
        return None

    project_root = find_project_root()
    if project_root is None:
        display.panel(
            "No .ai-sync.local.yaml or .ai-sync.yaml found. Create one first.",
            title="No project",
            style="error",
        )
        return None

    _warn_on_client_version_drift(display)
    context = build_plan_context(project_root, config_root, display)
    return PreparedProjectContext(project_root=project_root, plan_context=context)


def _ensure_installed(config_root: Path, display: Display) -> bool:
    if config_root.exists() and (config_root / "config.toml").exists():
        return True
    display.panel("Run `ai-sync install` first.", title="Not set up", style="error")
    return False


def _warn_on_client_version_drift(display: Display) -> None:
    versions_path = get_default_versions_path()
    ok, message = check_client_versions(versions_path)
    if not ok or message != "OK":
        display.print(f"Warning: {message}", style="warning")
