"""Service for StateStore-backed managed-output lifecycle."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

import tomli
import tomli_w
import yaml

from ai_sync.adapters.state_store import StateStore
from ai_sync.data_classes.write_spec import WriteSpec
from ai_sync.helpers import delete_at_path, ensure_dir, get_at_path, set_at_path

if TYPE_CHECKING:
    from ai_sync.data_classes.artifact import Artifact
    from ai_sync.data_classes.effect_spec import EffectSpec


class _DeleteSentinel:
    pass


DELETE = _DeleteSentinel()


class ManagedOutputService:
    """Apply managed writes, detect stale targets, and restore baselines."""

    def apply_resolved_artifacts(
        self,
        *,
        project_root: Path,
        entries: list[tuple["Artifact", list[WriteSpec]]],
        desired_targets: set[tuple[str, str, str]],
    ) -> None:
        store = self._load_store(project_root)
        all_specs: list[WriteSpec] = []
        spec_metadata: list[tuple[WriteSpec, "Artifact"]] = []

        for artifact, specs in entries:
            all_specs.extend(specs)
            for spec in specs:
                spec_metadata.append((spec, artifact))

        if all_specs:
            self.track_write_blocks(all_specs, store)

        for spec, artifact in spec_metadata:
            entry = store.get_entry(spec.file_path, spec.format, spec.target)
            if entry is not None:
                entry["kind"] = artifact.kind
                entry["resource"] = artifact.resource
                entry["name"] = artifact.name
                entry["description"] = artifact.description
                entry["source_alias"] = artifact.source_alias

        stale_delete_specs = self.build_stale_delete_specs(store, desired_targets)
        if stale_delete_specs:
            self.track_write_blocks(stale_delete_specs, store)
            self.cleanup_stale_entries(store, stale_delete_specs, desired_targets)

        store.save()

    def classify_plan_key_specs(
        self,
        *,
        project_root: Path,
        specs: list[WriteSpec],
    ) -> str:
        store = self._load_store(project_root)
        if not specs:
            return "unchanged"

        grouped: dict[tuple[str, str], list[WriteSpec]] = {}
        for spec in specs:
            grouped.setdefault((str(spec.file_path), spec.format), []).append(spec)

        statuses: list[str] = []
        for (file_path_str, fmt), file_specs in grouped.items():
            file_path = Path(file_path_str)
            if fmt == "text":
                statuses.append(
                    self._classify_text_specs(file_path=file_path, specs=file_specs, store=store)
                )
            else:
                statuses.append(
                    self._classify_structured_specs(file_path=file_path, fmt=fmt, specs=file_specs)
                )
        return self._aggregate_status(statuses)

    def list_stale_entries(
        self,
        *,
        project_root: Path,
        desired_targets: set[tuple[str, str, str]],
    ) -> list[dict]:
        store = self._load_store(project_root)
        return self._collect_stale_entries(store, desired_targets)

    def uninstall_project_outputs(
        self,
        *,
        project_root: Path,
        apply: bool,
    ) -> tuple[bool, bool]:
        store = self._load_store(project_root, strict_version=False)
        has_entries = bool(store.list_entries())
        has_effects = bool(store.list_effects())
        if not has_entries and not has_effects:
            return (False, False)

        did_change = self.restore_baselines(store, apply=apply)
        if apply:
            store.delete_state()
        return (True, did_change)

    def is_full_file_target(self, marker_id: str) -> bool:
        return (
            marker_id.startswith("ai-sync:agent:")
            or marker_id.startswith("ai-sync:skill:")
            or marker_id.startswith("ai-sync:command:")
            or marker_id.startswith("ai-sync:rule:")
            or marker_id == "ai-sync:env"
            or marker_id == "ai-sync:claude-import"
        )

    def renders_full_file(self, specs: list[WriteSpec]) -> bool:
        if not specs:
            return False
        return all(self.is_full_file_target(spec.target) for spec in specs)

    def render_text_specs(
        self,
        *,
        file_path: Path,
        specs: list[WriteSpec],
        original: str,
        store: StateStore,
    ) -> str:
        content = original
        if self.renders_full_file(specs):
            for spec in specs:
                if spec.value is DELETE:
                    entry = store.get_entry(file_path, "text", spec.target) or {}
                    baseline = entry.get("baseline", {}) if isinstance(entry, dict) else {}
                    if baseline.get("exists"):
                        blob_id = baseline.get("blob_id")
                        if isinstance(blob_id, str):
                            restored = store.fetch_blob(blob_id)
                            content = restored if restored is not None else ""
                        else:
                            content = original
                    else:
                        content = ""
                else:
                    content = str(spec.value)
            return content

        for spec in specs:
            if spec.value is DELETE:
                content = self._remove_marker_block(content, spec.target, file_path)
            else:
                content = self._apply_marker_block(content, spec.target, str(spec.value), file_path)
        return content

    def render_structured_specs(
        self,
        *,
        raw: str,
        fmt: str,
        specs: list[WriteSpec],
    ) -> str:
        data: object = self._parse_structured(raw, fmt)
        for spec in specs:
            if spec.value is DELETE:
                data = delete_at_path(data, spec.target)
            else:
                data = set_at_path(data, spec.target, spec.value)
        return self._dump_structured(data, fmt)

    # ------------------------------------------------------------------
    # Write lifecycle (absorbed from TrackedWriteService)
    # ------------------------------------------------------------------

    def track_write_blocks(self, specs: list[WriteSpec], store: StateStore) -> None:
        if not specs:
            return
        store.load()

        grouped: dict[Path, list[WriteSpec]] = {}
        for spec in specs:
            grouped.setdefault(spec.file_path, []).append(spec)

        for file_path, file_specs in grouped.items():
            formats = {spec.format for spec in file_specs}
            if len(formats) != 1:
                raise ValueError(f"Conflicting formats for {file_path}: {sorted(formats)}")
            fmt = file_specs[0].format
            if fmt == "text":
                self._apply_text_specs(file_path, file_specs, store)
            elif fmt in {"json", "toml", "yaml"}:
                self._apply_structured_specs(file_path, file_specs, store)
            else:
                raise ValueError(f"Unsupported format: {fmt}")

        store.save()

    # ------------------------------------------------------------------
    # Stale-target detection (absorbed from ApplyService)
    # ------------------------------------------------------------------

    def build_stale_delete_specs(
        self,
        store: StateStore,
        desired_targets: set[tuple[str, str, str]],
    ) -> list[WriteSpec]:
        return [
            WriteSpec(
                file_path=Path(entry["file_path"]),
                format=entry["format"],
                target=entry["target"],
                value=DELETE,
            )
            for entry in self._collect_stale_entries(store, desired_targets)
        ]

    def cleanup_stale_entries(
        self,
        store: StateStore,
        stale_specs: list[WriteSpec],
        desired_targets: set[tuple[str, str, str]],
    ) -> None:
        """Remove stale state entries and clean up empty files/directories."""
        dirs_to_clean: set[Path] = set()
        desired_file_paths = {fp for fp, _, _ in desired_targets}
        for spec in stale_specs:
            file_path = spec.file_path
            store.remove_entry(file_path, spec.format, spec.target)
            if str(file_path) in desired_file_paths:
                continue
            if file_path.is_file() and not file_path.read_text(encoding="utf-8").strip():
                file_path.unlink(missing_ok=True)
                dirs_to_clean.add(file_path.parent)
        for d in sorted(dirs_to_clean, key=lambda p: len(p.parts), reverse=True):
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()

    # ------------------------------------------------------------------
    # Baseline restoration (absorbed from UninstallService)
    # ------------------------------------------------------------------

    def restore_baselines(self, store: StateStore, *, apply: bool) -> bool:
        """Restore tracked baselines to their pre-managed state.

        Returns True if any file content would change.
        """
        entries = store.list_entries()
        grouped: dict[tuple[str, str], list[dict]] = {}
        for entry in entries:
            file_path = entry.get("file_path")
            fmt = entry.get("format")
            target = entry.get("target")
            baseline = entry.get("baseline")
            if (
                not isinstance(file_path, str)
                or not isinstance(fmt, str)
                or not isinstance(target, str)
            ):
                continue
            if not isinstance(baseline, dict):
                continue
            grouped.setdefault((file_path, fmt), []).append(entry)

        did_change = False
        for (file_path_str, fmt), file_entries in grouped.items():
            file_path = Path(file_path_str)
            if fmt == "text":
                did_change |= self._restore_text_baselines(
                    store, file_path, file_entries, apply=apply
                )
            elif fmt in {"json", "toml", "yaml"}:
                did_change |= self._restore_structured_baselines(
                    store, file_path, file_entries, fmt, apply=apply
                )
            else:
                print(f"Skipping unsupported format in state: {fmt}")
        return did_change

    # ------------------------------------------------------------------
    # Internal: text write helpers
    # ------------------------------------------------------------------

    def _apply_text_specs(
        self, file_path: Path, specs: list[WriteSpec], store: StateStore
    ) -> None:
        content = ""
        if file_path.exists():
            try:
                content = file_path.read_text(encoding="utf-8")
            except OSError:
                content = ""
        original = content
        if self.renders_full_file(specs):
            self._apply_full_file_text_specs(file_path, specs, store, original)
            return
        for spec in specs:
            marker_id = spec.target
            entry = store.get_entry(file_path, "text", marker_id)
            if entry is None or not entry.get("baseline"):
                existing_block = self._extract_marker_block(content, marker_id, file_path)
                if existing_block is None:
                    store.record_baseline(
                        file_path, "text", marker_id, exists=False, content=None
                    )
                else:
                    store.record_baseline(
                        file_path, "text", marker_id, exists=True, content=existing_block
                    )
            if spec.value is DELETE:
                content = self._remove_marker_block(content, marker_id, file_path)
            else:
                block_body = str(spec.value)
                content = self._apply_marker_block(content, marker_id, block_body, file_path)

        if content != original:
            ensure_dir(file_path.parent)
            self._write_atomic(file_path, content)

    def _apply_full_file_text_specs(
        self,
        file_path: Path,
        specs: list[WriteSpec],
        store: StateStore,
        original: str,
    ) -> None:
        content = original
        for spec in specs:
            marker_id = spec.target
            entry = store.get_entry(file_path, "text", marker_id)
            if entry is None or not entry.get("baseline"):
                if file_path.exists():
                    store.record_baseline(
                        file_path, "text", marker_id, exists=True, content=original
                    )
                else:
                    store.record_baseline(
                        file_path, "text", marker_id, exists=False, content=None
                    )
            if spec.value is DELETE:
                entry = store.get_entry(file_path, "text", marker_id) or {}
                baseline = entry.get("baseline", {}) if isinstance(entry, dict) else {}
                if baseline.get("exists"):
                    blob_id = baseline.get("blob_id")
                    if isinstance(blob_id, str):
                        restored = store.fetch_blob(blob_id)
                        if restored is not None:
                            content = restored
                            continue
                content = ""
            else:
                content = str(spec.value)

        if content != original:
            ensure_dir(file_path.parent)
            self._write_atomic(file_path, content)

    # ------------------------------------------------------------------
    # Internal: structured write helpers
    # ------------------------------------------------------------------

    def _apply_structured_specs(
        self, file_path: Path, specs: list[WriteSpec], store: StateStore
    ) -> None:
        data: object
        if file_path.exists():
            raw = file_path.read_text(encoding="utf-8")
        else:
            raw = ""
        data = self._parse_structured(raw, specs[0].format)
        for spec in specs:
            pointer = spec.target
            entry = store.get_entry(file_path, spec.format, pointer)
            if entry is None or not entry.get("baseline"):
                try:
                    existing = get_at_path(data, pointer)
                    exists = True
                except KeyError:
                    existing = None
                    exists = False
                if exists:
                    store.record_baseline(
                        file_path,
                        spec.format,
                        pointer,
                        exists=True,
                        content=self._serialize_value(existing),
                    )
                else:
                    store.record_baseline(
                        file_path, spec.format, pointer, exists=False, content=None
                    )
            if spec.value is DELETE:
                data = delete_at_path(data, pointer)
            else:
                data = set_at_path(data, pointer, spec.value)

        new_content = self._dump_structured(data, specs[0].format)
        if new_content != raw:
            ensure_dir(file_path.parent)
            self._write_atomic(file_path, new_content)

    # ------------------------------------------------------------------
    # Internal: baseline restoration helpers
    # ------------------------------------------------------------------

    def _restore_text_baselines(
        self,
        store: StateStore,
        file_path: Path,
        file_entries: list[dict],
        *,
        apply: bool,
    ) -> bool:
        content = ""
        if file_path.exists():
            try:
                content = file_path.read_text(encoding="utf-8")
            except OSError:
                content = ""
        original = content
        any_baseline = False
        for entry in file_entries:
            marker_id = entry["target"]
            baseline = entry.get("baseline", {})
            if self.is_full_file_target(marker_id):
                if baseline.get("exists"):
                    any_baseline = True
                    blob_id = baseline.get("blob_id")
                    if isinstance(blob_id, str):
                        blob = store.fetch_blob(blob_id)
                        if blob is not None:
                            content = blob
                else:
                    content = ""
                continue
            if baseline.get("exists"):
                any_baseline = True
                blob_id = baseline.get("blob_id")
                if isinstance(blob_id, str):
                    blob = store.fetch_blob(blob_id)
                    if blob is not None:
                        content = self._restore_marker_block(
                            content, marker_id, blob, file_path
                        )
            else:
                content = self._remove_marker_block(content, marker_id, file_path)
        if content != original:
            if apply:
                if not content.strip() and not any_baseline:
                    file_path.unlink(missing_ok=True)
                else:
                    ensure_dir(file_path.parent)
                    self._write_atomic(file_path, content)
            return True
        return False

    def _restore_structured_baselines(
        self,
        store: StateStore,
        file_path: Path,
        file_entries: list[dict],
        fmt: str,
        *,
        apply: bool,
    ) -> bool:
        raw = file_path.read_text(encoding="utf-8") if file_path.exists() else ""
        data: object = self._parse_structured(raw, fmt)
        any_baseline = False
        for entry in file_entries:
            pointer = entry["target"]
            baseline = entry.get("baseline", {})
            if baseline.get("exists"):
                any_baseline = True
                blob_id = baseline.get("blob_id")
                if isinstance(blob_id, str):
                    blob = store.fetch_blob(blob_id)
                    if blob is not None:
                        value = self._deserialize_value(blob)
                        data = set_at_path(data, pointer, value)
            else:
                data = delete_at_path(data, pointer)
        new_content = self._dump_structured(data, fmt)
        if new_content != raw:
            if apply:
                if self._is_empty_structured(data) and not any_baseline:
                    file_path.unlink(missing_ok=True)
                else:
                    ensure_dir(file_path.parent)
                    self._write_atomic(file_path, new_content)
            return True
        return False

    def _restore_marker_block(
        self, content: str, marker_id: str, baseline_block: str, file_path: Path
    ) -> str:
        begin, end = self._marker_bounds(file_path, marker_id)
        pattern = re.compile(rf"{re.escape(begin)}.*?{re.escape(end)}", re.DOTALL)
        if pattern.search(content):
            return pattern.sub(baseline_block, content)
        if content.strip():
            return content.rstrip() + "\n\n" + baseline_block + "\n"
        return baseline_block + "\n"

    def _remove_marker_block(
        self, content: str, marker_id: str, file_path: Path
    ) -> str:
        begin, end = self._marker_bounds(file_path, marker_id)
        pattern = re.compile(rf"{re.escape(begin)}.*?{re.escape(end)}\n?", re.DOTALL)
        cleaned = pattern.sub("", content)
        if self._marker_style_for_path(file_path) == "html" and self._is_frontmatter_only(cleaned):
            return ""
        return cleaned.strip() + "\n" if cleaned.strip() else ""

    def _apply_marker_block(
        self, content: str, marker_id: str, block_body: str, file_path: Path
    ) -> str:
        begin, end = self._marker_bounds(file_path, marker_id)
        style = self._marker_style_for_path(file_path)
        if style == "html":
            frontmatter, body = self._split_frontmatter(block_body)
            if frontmatter is not None:
                body = body.lstrip("\n")
                block = f"{begin}\n{body.rstrip()}\n{end}"
                pattern = re.compile(rf"{re.escape(begin)}.*?{re.escape(end)}", re.DOTALL)
                if pattern.search(content):
                    replaced = pattern.sub(lambda _: block, content)
                    existing_front, rest = self._split_frontmatter(replaced)
                    if existing_front is not None:
                        rest = rest.lstrip("\n")
                        combined = f"{frontmatter}\n\n{rest}" if rest else f"{frontmatter}\n"
                        return combined if combined.endswith("\n") else combined + "\n"
                    combined = f"{frontmatter}\n\n{replaced.lstrip()}"
                    return combined if combined.endswith("\n") else combined + "\n"
                if content.strip():
                    existing_front, rest = self._split_frontmatter(content)
                    if existing_front is not None:
                        rest = rest.lstrip("\n")
                        combined = f"{frontmatter}\n\n{block}"
                        if rest:
                            combined = f"{combined}\n\n{rest.rstrip()}"
                        return combined.rstrip() + "\n"
                    return content.rstrip() + "\n\n" + f"{frontmatter}\n\n{block}\n"
                return f"{frontmatter}\n\n{block}\n"

        block = f"{begin}\n{block_body.rstrip()}\n{end}"
        pattern = re.compile(rf"{re.escape(begin)}.*?{re.escape(end)}", re.DOTALL)
        if pattern.search(content):
            return pattern.sub(lambda _: block, content)
        if content.strip():
            return content.rstrip() + "\n\n" + block + "\n"
        return block + "\n"

    def _extract_marker_block(
        self, content: str, marker_id: str, file_path: Path
    ) -> str | None:
        begin, end = self._marker_bounds(file_path, marker_id)
        pattern = re.compile(rf"{re.escape(begin)}.*?{re.escape(end)}", re.DOTALL)
        match = pattern.search(content)
        return match.group(0) if match else None

    def _marker_bounds(self, file_path: Path, marker_id: str) -> tuple[str, str]:
        style = self._marker_style_for_path(file_path)
        if style == "html":
            return f"<!-- BEGIN {marker_id} -->", f"<!-- END {marker_id} -->"
        if style == "slash":
            return f"// BEGIN {marker_id}", f"// END {marker_id}"
        if style == "block":
            return f"/* BEGIN {marker_id} */", f"/* END {marker_id} */"
        return f"# BEGIN {marker_id}", f"# END {marker_id}"

    @staticmethod
    def _marker_style_for_path(file_path: Path) -> str:
        name = file_path.name.lower()
        ext = file_path.suffix.lower()
        if ext in {".md", ".mdc", ".markdown", ".mdx"}:
            return "html"
        if name.endswith(".env") or ext in {
            ".env",
            ".sh",
            ".bash",
            ".zsh",
            ".fish",
            ".py",
            ".rb",
            ".pl",
            ".ps1",
        }:
            return "hash"
        if ext in {".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cc", ".cpp", ".go", ".rs"}:
            return "slash"
        if ext in {".css", ".scss", ".less"}:
            return "block"
        return "hash"

    @staticmethod
    def _split_frontmatter(content: str) -> tuple[str | None, str]:
        if not content.startswith("---"):
            return None, content
        lines = content.splitlines(keepends=True)
        if not lines or lines[0].strip() != "---":
            return None, content
        for idx in range(1, len(lines)):
            if lines[idx].strip() in ("---", "..."):
                front = "".join(lines[: idx + 1]).rstrip("\n")
                rest = "".join(lines[idx + 1 :])
                return front, rest
        return None, content

    def _is_frontmatter_only(self, content: str) -> bool:
        frontmatter, rest = self._split_frontmatter(content)
        if frontmatter is None:
            return False
        return not rest.strip()

    @staticmethod
    def _parse_structured(raw: str, format: str) -> dict | list:
        if not raw.strip():
            return {}
        if format == "json":
            try:
                data = json.loads(raw)
                return data if isinstance(data, (dict, list)) else {}
            except json.JSONDecodeError:
                return {}
        if format == "toml":
            try:
                data = tomli.loads(raw)
                return data if isinstance(data, dict) else {}
            except tomli.TOMLDecodeError:
                return {}
        if format == "yaml":
            try:
                data = yaml.safe_load(raw)
                return data if isinstance(data, (dict, list)) else {}
            except yaml.YAMLError:
                return {}
        raise ValueError(f"Unsupported format: {format}")

    @staticmethod
    def _dump_structured(data: object, format: str) -> str:
        if format == "json":
            return json.dumps(data, indent=2)
        if format == "toml":
            return tomli_w.dumps(data if isinstance(data, dict) else {})
        if format == "yaml":
            return yaml.safe_dump(data, sort_keys=False).rstrip() + "\n"
        raise ValueError(f"Unsupported format: {format}")

    @staticmethod
    def _serialize_value(value: object) -> str:
        try:
            return json.dumps(value, sort_keys=True)
        except TypeError:
            return yaml.safe_dump(value, sort_keys=False)

    def _deserialize_value(self, blob: str) -> object:
        try:
            return json.loads(blob)
        except json.JSONDecodeError:
            try:
                return yaml.safe_load(blob)
            except yaml.YAMLError:
                return blob

    def _is_empty_structured(self, data: object) -> bool:
        if isinstance(data, dict):
            return len(data) == 0
        if isinstance(data, list):
            return len(data) == 0
        return True

    def _collect_stale_entries(
        self,
        store: StateStore,
        desired_targets: set[tuple[str, str, str]],
    ) -> list[dict]:
        desired_targets_by_file: dict[tuple[str, str], set[str]] = {}
        for file_path, fmt, target in desired_targets:
            desired_targets_by_file.setdefault((file_path, fmt), set()).add(target)

        stale_entries: list[dict] = []
        for entry in store.list_entries():
            file_path = entry.get("file_path")
            fmt = entry.get("format")
            target = entry.get("target")
            if (
                not isinstance(file_path, str)
                or not isinstance(fmt, str)
                or not isinstance(target, str)
            ):
                continue
            if (file_path, fmt, target) in desired_targets:
                continue
            same_file_targets = desired_targets_by_file.get((file_path, fmt), set())
            if self.is_full_file_target(target) and any(
                other != target for other in same_file_targets
            ):
                continue
            stale_entries.append(entry)
        return stale_entries

    def _classify_text_specs(
        self,
        *,
        file_path: Path,
        specs: list[WriteSpec],
        store: StateStore,
    ) -> str:
        original = file_path.read_text(encoding="utf-8") if file_path.exists() else ""
        content = self.render_text_specs(
            file_path=file_path,
            specs=specs,
            original=original,
            store=store,
        )
        if content == original:
            return "unchanged"
        if not original and content:
            return "create"
        if original and not content:
            return "delete"
        return "update"

    def _classify_structured_specs(
        self,
        *,
        file_path: Path,
        fmt: str,
        specs: list[WriteSpec],
    ) -> str:
        raw = file_path.read_text(encoding="utf-8") if file_path.exists() else ""
        new_content = self.render_structured_specs(raw=raw, fmt=fmt, specs=specs)
        if new_content == raw:
            return "unchanged"
        if not raw and new_content:
            return "create"
        if raw and not new_content.strip():
            return "delete"
        return "update"

    @staticmethod
    def _aggregate_status(statuses: list[str]) -> str:
        changed = [status for status in statuses if status != "unchanged"]
        if not changed:
            return "unchanged"
        if all(status == "create" for status in changed):
            return "create"
        if all(status == "delete" for status in changed):
            return "delete"
        return "update"

    def record_and_save_effects(
        self,
        *,
        project_root: Path,
        effects: list[tuple["EffectSpec", dict]],
    ) -> None:
        """Persist effect baselines into the shared state store."""
        store = self._load_store(project_root)
        for effect, baseline in effects:
            store.record_effect(
                effect_type=effect.effect_type,
                target=effect.target,
                target_key=effect.target_key,
                baseline=baseline,
            )
        store.save()

    @staticmethod
    def _load_store(project_root: Path, *, strict_version: bool = True) -> StateStore:
        store = StateStore(project_root)
        store.load()
        if strict_version:
            store.check_version()
        return store

    @staticmethod
    def _write_atomic(path: Path, content: str) -> None:
        tmp = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as file_handle:
                file_handle.write(content)
            tmp.replace(path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
