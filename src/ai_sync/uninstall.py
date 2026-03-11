"""Uninstall ai-sync managed changes from a project."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from .git_safety import remove_pre_commit_hook
from .helpers import ensure_dir
from .path_ops import delete_at_path, set_at_path
from .state_store import StateStore
from .track_write import (
    _dump_structured,
    _is_full_file_target,
    _parse_structured,
    _write_atomic,
    marker_bounds,
)


def run_uninstall(project_root: Path, *, apply: bool) -> int:
    store = StateStore(project_root)
    store.load()
    entries = store.list_entries()
    if not entries:
        print("No ai-sync state found.")
        return 0

    grouped: dict[tuple[str, str], list[dict]] = {}
    for entry in entries:
        file_path = entry.get("file_path")
        fmt = entry.get("format")
        target = entry.get("target")
        baseline = entry.get("baseline")
        if not isinstance(file_path, str) or not isinstance(fmt, str) or not isinstance(target, str):
            continue
        if not isinstance(baseline, dict):
            continue
        grouped.setdefault((file_path, fmt), []).append(entry)

    did_change = False
    for (file_path_str, fmt), file_entries in grouped.items():
        file_path = Path(file_path_str)
        if fmt == "text":
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
                if _is_full_file_target(marker_id):
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
                            content = _restore_marker_block(content, marker_id, blob, file_path)
                else:
                    content = _remove_marker_block(content, marker_id, file_path)
            if content != original:
                did_change = True
                if apply:
                    if not content.strip() and not any_baseline:
                        file_path.unlink(missing_ok=True)
                    else:
                        ensure_dir(file_path.parent)
                        _write_atomic(file_path, content)
        elif fmt in {"json", "toml", "yaml"}:
            raw = file_path.read_text(encoding="utf-8") if file_path.exists() else ""
            data: object = _parse_structured(raw, fmt)
            original = raw
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
                            value = _deserialize_value(blob)
                            data = set_at_path(data, pointer, value)
                else:
                    data = delete_at_path(data, pointer)
            new_content = _dump_structured(data, fmt)
            if new_content != original:
                did_change = True
                if apply:
                    if _is_empty_structured(data) and not any_baseline:
                        file_path.unlink(missing_ok=True)
                    else:
                        ensure_dir(file_path.parent)
                        _write_atomic(file_path, new_content)
        else:
            print(f"Skipping unsupported format in state: {fmt}")

    if apply:
        if remove_pre_commit_hook(project_root):
            print("Removed ai-sync pre-commit hook.")
        store.delete_state()
        print("ai-sync state removed.")
    if not apply:
        print("Dry run complete. Use --apply to make changes.")
    if did_change:
        print("ai-sync uninstall complete.")
    else:
        print("No tracked changes found to remove.")
    return 0


def _restore_marker_block(content: str, marker_id: str, baseline_block: str, file_path: Path) -> str:
    begin, end = marker_bounds(file_path, marker_id)
    pattern = re.compile(rf"{re.escape(begin)}.*?{re.escape(end)}", re.DOTALL)
    if pattern.search(content):
        return pattern.sub(baseline_block, content)
    if content.strip():
        return content.rstrip() + "\n\n" + baseline_block + "\n"
    return baseline_block + "\n"


def _remove_marker_block(content: str, marker_id: str, file_path: Path) -> str:
    begin, end = marker_bounds(file_path, marker_id)
    pattern = re.compile(rf"{re.escape(begin)}.*?{re.escape(end)}\n?", re.DOTALL)
    cleaned = pattern.sub("", content)
    return cleaned.strip() + "\n" if cleaned.strip() else ""


def _deserialize_value(blob: str) -> object:
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        try:
            return yaml.safe_load(blob)
        except yaml.YAMLError:
            return blob


def _is_empty_structured(data: object) -> bool:
    if isinstance(data, dict):
        return len(data) == 0
    if isinstance(data, list):
        return len(data) == 0
    return True
