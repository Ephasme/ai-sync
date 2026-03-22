"""Service for the doctor command."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from ai_sync.services.config_store_service import ConfigStoreService
from ai_sync.services.display_service import DisplayService
from ai_sync.services.git_safety_service import GitSafetyService
from ai_sync.services.plan_service import PlanService
from ai_sync.services.project_locator_service import ProjectLocatorService
from ai_sync.services.project_manifest_service import ProjectManifestService


class DoctorService:
    """Check machine bootstrap and project planning health."""

    def __init__(
        self,
        *,
        config_store_service: ConfigStoreService,
        git_safety_service: GitSafetyService,
        project_locator_service: ProjectLocatorService,
        project_manifest_service: ProjectManifestService,
        plan_service: PlanService,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._config_store_service = config_store_service
        self._git_safety_service = git_safety_service
        self._project_locator_service = project_locator_service
        self._project_manifest_service = project_manifest_service
        self._plan_service = plan_service
        self._environ = os.environ if environ is None else environ

    def run(self, *, config_root: Path, display: DisplayService) -> int:
        display.print(f"Config root: {config_root}")
        if not config_root.exists():
            display.print("  Missing config root. Run `ai-sync install`.", style="warning")
            return 1

        config_path = config_root / "config.toml"
        if not config_path.exists():
            display.print("  Missing config.toml. Run `ai-sync install`.", style="warning")
            return 1

        try:
            config = self._config_store_service.load_config(config_root)
        except RuntimeError as exc:
            display.print(f"  Failed to read config: {exc}", style="warning")
            return 1

        op_account_identifier = self._environ.get("OP_ACCOUNT") or config.get(
            "op_account_identifier"
        )
        token = self._environ.get("OP_SERVICE_ACCOUNT_TOKEN")
        if token:
            display.print("  1Password auth: OK (service account token)", style="success")
        elif op_account_identifier:
            display.print(
                f"  1Password auth: OK (OP_ACCOUNT={op_account_identifier})", style="success"
            )
        else:
            display.print(
                "  1Password auth: missing "
                "(set OP_SERVICE_ACCOUNT_TOKEN or OP_ACCOUNT to a sign-in address or user ID)",
                style="warning",
            )
            return 1

        project_root = self._project_locator_service.find_project_root()
        if project_root is None:
            display.print(
                "\nNo project found (no .ai-sync.local.yaml or .ai-sync.yaml "
                "in current directory tree)",
                style="dim",
            )
            return 0

        display.print(f"\nProject: {project_root}")
        try:
            manifest_path = self._project_manifest_service.resolve_project_manifest_path(
                project_root
            )
            manifest = self._project_manifest_service.resolve_project_manifest(project_root)
            display.print(
                f"  {manifest_path.name}: OK ({len(manifest.sources)} sources declared)",
                style="success",
            )
        except RuntimeError as exc:
            display.print(f"  project manifest: {exc}", style="warning")
            return 1

        uncovered = self._git_safety_service.check_gitignore(project_root)
        if uncovered:
            display.print(
                f"  Gitignore: MISSING coverage for {', '.join(uncovered)}", style="warning"
            )
        else:
            display.print("  Gitignore: OK", style="success")

        try:
            context = self._plan_service.assemble_plan_context(
                project_root, config_root, display
            )
            hook_status = self._git_safety_service.check_pre_commit_hook(project_root)
            requires_local_hook = context.runtime_env.has_sensitive_deps
            if hook_status == "not-git-repo":
                display.print("  Pre-commit hook: skipped (not a git repo)", style="dim")
            elif requires_local_hook and hook_status == "installed":
                display.print("  Pre-commit hook: OK", style="success")
            elif requires_local_hook and hook_status == "missing":
                display.print(
                    "  Pre-commit hook: not installed (run `ai-sync apply` to install)",
                    style="warning",
                )
            elif not requires_local_hook and hook_status == "installed":
                display.print(
                    "  Pre-commit hook: installed but not needed for current selections",
                    style="dim",
                )
            else:
                display.print("  Pre-commit hook: not needed for current selections", style="dim")
            display.print(
                f"  Planned: {len(context.plan.actions)} action(s) "
                f"from {len(context.resolved_sources)} source(s)",
                style="success",
            )
        except RuntimeError as exc:
            display.print(f"  Plan check failed: {exc}", style="warning")

        return 0
