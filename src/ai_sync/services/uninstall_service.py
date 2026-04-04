"""Service for the uninstall command.

Removes **all** ai-sync generated outputs from the project while preserving
the YAML manifest files (`.ai-sync.yaml`, `.ai-sync.local.yaml`).
"""

from __future__ import annotations

import shutil
from pathlib import Path

from ai_sync.adapters.state_store import StateStore
from ai_sync.services.display_service import DisplayService
from ai_sync.services.git_safety_service import GitSafetyService
from ai_sync.services.managed_output_service import ManagedOutputService
from ai_sync.services.project_locator_service import ProjectLocatorService

_CLIENT_DIRS = (".cursor", ".codex", ".gemini", ".claude")


class UninstallService:
    """Remove all ai-sync generated outputs from a project."""

    def __init__(
        self,
        *,
        git_safety_service: GitSafetyService,
        project_locator_service: ProjectLocatorService,
        managed_output_service: ManagedOutputService,
    ) -> None:
        self._git_safety_service = git_safety_service
        self._project_locator_service = project_locator_service
        self._managed_output_service = managed_output_service

    def run(self, *, display: DisplayService, apply: bool) -> int:
        """Execute the uninstall command: locate project and remove all generated outputs."""
        project_root = self._project_locator_service.find_project_root()
        if project_root is None:
            display.panel(
                "No .ai-sync.local.yaml or .ai-sync.yaml found. Nothing to uninstall.",
                title="No project",
                style="error",
            )
            return 1
        return self.run_uninstall(project_root, apply=apply)

    def run_uninstall(self, project_root: Path, *, apply: bool) -> int:
        ai_sync_dir = project_root / ".ai-sync"

        # Phase 1: state-driven baseline restoration (undo managed file changes).
        peek = StateStore(project_root)
        peek.load()
        has_state = bool(peek.list_entries()) or bool(peek.list_effects())

        did_change = False
        if has_state:
            if apply:
                self._restore_effects(project_root)
            _, did_change = self._managed_output_service.uninstall_project_outputs(
                project_root=project_root,
                apply=apply,
            )

        # Phase 2: remove pre-commit hook even when no state tracks it.
        if not has_state:
            if self._git_safety_service.remove_pre_commit_hook(project_root):
                if apply:
                    print("Removed ai-sync pre-commit hook.")
                did_change = True

        # Phase 3: remove the entire .ai-sync/ directory (sources, rules, plans, …).
        if ai_sync_dir.is_dir():
            if apply:
                shutil.rmtree(ai_sync_dir, ignore_errors=True)
            did_change = True

        # Phase 4: prune client directories that are now empty.
        for name in _CLIENT_DIRS:
            did_change |= self._prune_empty_tree(project_root / name, apply=apply)

        if not did_change:
            print("Nothing to uninstall.")
            return 0

        if apply:
            print("ai-sync uninstall complete.")
        else:
            print("Dry run complete. Use --apply to make changes.")
        return 0

    @staticmethod
    def _prune_empty_tree(root: Path, *, apply: bool) -> bool:
        """Remove *root* if it contains only empty directories. Returns True when prunable."""
        if not root.is_dir():
            return False
        if any(child.is_file() for child in root.rglob("*")):
            return False
        if apply:
            shutil.rmtree(root, ignore_errors=True)
        return True

    def _restore_effects(self, project_root: Path) -> None:
        """Reverse tracked effects using their stored baselines."""
        store = StateStore(project_root)
        store.load()
        for effect in store.list_effects():
            effect_type = effect.get("effect_type")
            baseline = effect.get("baseline", {})
            if effect_type == "pre-commit-hook-install":
                if self._git_safety_service.remove_pre_commit_hook(project_root):
                    print("Removed ai-sync pre-commit hook.")
            elif effect_type == "pre-commit-hook-remove":
                if baseline.get("had_prior_hook"):
                    print(
                        "Note: Prior pre-commit hook was removed by ai-sync. "
                        "If you had a custom hook, restore it manually."
                    )
            elif effect_type == "chmod":
                prior_mode = baseline.get("prior_mode")
                if prior_mode is not None:
                    path = Path(effect.get("target", ""))
                    try:
                        if path.exists():
                            path.chmod(prior_mode)
                    except OSError:
                        pass
