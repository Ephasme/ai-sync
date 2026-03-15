"""Service for plan persistence, validation, and rendering."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ai_sync.models import PLAN_SCHEMA_VERSION, ApplyPlan
from ai_sync.models.plan_action import PlanAction
from ai_sync.services.display_service import DisplayService, PrintStyle

_ACTION_DISPLAY: dict[str, tuple[str, PrintStyle]] = {
    "create": ("+", "success"),
    "update": ("~", "warning"),
    "delete": ("-", "danger"),
}

_CLIENT_ORDER = {name: idx for idx, name in enumerate(("cursor", "claude", "codex", "gemini", "global"))}


class PlanPersistenceService:
    """Persist, validate, and render computed apply plans."""

    def default_plan_path(self, project_root: Path) -> Path:
        return project_root / ".ai-sync" / "last-plan.yaml"

    def save_plan(self, plan: ApplyPlan, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(plan.model_dump(), sort_keys=False), encoding="utf-8")

    def load_plan(self, path: Path) -> ApplyPlan:
        if not path.exists():
            raise RuntimeError(f"Plan file not found: {path}")
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise RuntimeError(f"Failed to parse plan file {path}: {exc}") from exc
        return ApplyPlan.model_validate(data)

    def validate_saved_plan(self, path: Path, current: ApplyPlan) -> ApplyPlan:
        saved = self.load_plan(path)
        if saved.schema_version != PLAN_SCHEMA_VERSION:
            raise RuntimeError(
                f"Plan file schema version {saved.schema_version} is not supported by this ai-sync version."
            )
        if self._normalized_plan(saved) != self._normalized_plan(current):
            raise RuntimeError(
                "Saved plan is no longer valid. Regenerate it because the manifest, "
                "sources, or planned actions changed."
            )
        return saved

    def render_plan(self, plan: ApplyPlan, display: DisplayService) -> None:
        display.print("")
        self._render_sources(plan, display)
        display.print("")
        self._render_actions(plan, display)

    def _render_sources(self, plan: ApplyPlan, display: DisplayService) -> None:
        display.rule("Planned Sources", style="info")
        source_rows = [
            (
                source.alias,
                source.kind,
                source.version or "local",
                source.fingerprint[:12],
            )
            for source in plan.sources
        ]
        if source_rows:
            display.table(("Alias", "Kind", "Version", "Fingerprint"), source_rows)
        else:
            display.print("  No sources selected.", style="dim")

        for source in plan.sources:
            if source.portability_warning:
                display.print(
                    f"  Warning: {source.alias}: {source.portability_warning}",
                    style="warning",
                )

    def _render_actions(self, plan: ApplyPlan, display: DisplayService) -> None:
        display.rule("Planned Changes", style="info")

        if not plan.actions:
            display.print("")
            display.panel(
                "Your project outputs are up to date.\n"
                "ai-sync found no differences between your manifest and current outputs.",
                title="No changes",
                style="success",
            )
            return

        artifact_groups: dict[tuple[str, str], list[PlanAction]] = {}
        for action in plan.actions:
            key = (action.kind, action.resource)
            artifact_groups.setdefault(key, []).append(action)

        max_client = max(len(a.client) for a in plan.actions)

        for (kind, resource), actions in artifact_groups.items():
            heading = actions[0].name or resource
            display.print(f"\n  {kind}  {heading}", style="info")
            if heading != resource:
                display.print(f"    {resource}", style="dim")
            if actions[0].description:
                display.print(f"    {actions[0].description}", style="dim")
            ordered = _sort_by_client(actions)
            for action in ordered:
                symbol, style = _ACTION_DISPLAY.get(action.action, ("?", "normal"))
                rel_target = _relative_target(action.target, plan.project_root)
                suffix = " (secret)" if action.secret_backed else ""
                line = f"    {symbol} {action.client:<{max_client}}  -> {rel_target}{suffix}"
                display.print(line, style=style)

        self._render_summary(plan.actions, display)

    @staticmethod
    def _render_summary(actions: list[PlanAction], display: DisplayService) -> None:
        counts: dict[str, int] = {}
        for action in actions:
            counts[action.action] = counts.get(action.action, 0) + 1

        parts = []
        for action_type in ("create", "update", "delete"):
            count = counts.get(action_type, 0)
            if count:
                parts.append(f"{count} to {action_type}")

        display.print("")
        display.print(f"Plan: {', '.join(parts)}.", style="info")

    @staticmethod
    def _normalized_plan(plan: ApplyPlan) -> dict[str, Any]:
        data = plan.model_dump()
        data.pop("created_at", None)
        return data


def _sort_by_client(actions: list[PlanAction]) -> list[PlanAction]:
    fallback = len(_CLIENT_ORDER)
    return sorted(actions, key=lambda a: _CLIENT_ORDER.get(a.client, fallback))


def _relative_target(target: str, project_root: str) -> str:
    """Convert absolute target path to project-relative when possible."""
    root = project_root.rstrip("/\\")
    if target.startswith(root + "/") or target.startswith(root + "\\"):
        return target[len(root) + 1 :]
    return target
