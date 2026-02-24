"""Tracked write operations for ai-sync."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

import tomli
import tomli_w
import yaml

from .helpers import ensure_dir
from .path_ops import delete_at_path, get_at_path, set_at_path
from .state_store import StateStore


@dataclass(frozen=True)
class WriteSpec:
    file_path: Path
    format: str
    target: str
    value: object


class _DeleteSentinel:
    pass


DELETE = _DeleteSentinel()


def track_write_blocks(specs: list[WriteSpec]) -> None:
    if not specs:
        return
    store = StateStore()
    store.load()

    grouped: dict[Path, list[WriteSpec]] = {}
    for spec in specs:
        grouped.setdefault(spec.file_path, []).append(spec)

    for file_path, file_specs in grouped.items():
        formats = {spec.format for spec in file_specs}
        if len(formats) != 1:
            raise ValueError(f"Conflicting formats for {file_path}: {sorted(formats)}")
        format = file_specs[0].format
        if format == "text":
            _apply_text_specs(file_path, file_specs, store)
        elif format in {"json", "toml", "yaml"}:
            _apply_structured_specs(file_path, file_specs, store)
        else:
            raise ValueError(f"Unsupported format: {format}")

    store.save()


def _apply_text_specs(file_path: Path, specs: list[WriteSpec], store: StateStore) -> None:
    content = ""
    if file_path.exists():
        try:
            content = file_path.read_text(encoding="utf-8")
        except OSError:
            content = ""
    original = content
    for spec in specs:
        marker_id = spec.target
        entry = store.get_entry(file_path, "text", marker_id)
        if entry is None or not entry.get("baseline"):
            existing_block = _extract_marker_block(content, marker_id, file_path)
            if existing_block is None:
                store.record_baseline(file_path, "text", marker_id, exists=False, content=None)
            else:
                store.record_baseline(file_path, "text", marker_id, exists=True, content=existing_block)
        if spec.value is DELETE:
            content = remove_marker_block(content, marker_id, file_path)
        else:
            block_body = str(spec.value)
            content = apply_marker_block(content, marker_id, block_body, file_path)

    if content != original:
        ensure_dir(file_path.parent)
        _write_atomic(file_path, content)


def _apply_structured_specs(file_path: Path, specs: list[WriteSpec], store: StateStore) -> None:
    data: object
    if file_path.exists():
        raw = file_path.read_text(encoding="utf-8")
    else:
        raw = ""
    data = _parse_structured(raw, specs[0].format)
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
                    content=_serialize_value(existing),
                )
            else:
                store.record_baseline(file_path, spec.format, pointer, exists=False, content=None)
        if spec.value is DELETE:
            data = delete_at_path(data, pointer)
        else:
            data = set_at_path(data, pointer, spec.value)

    new_content = _dump_structured(data, specs[0].format)
    if new_content != raw:
        ensure_dir(file_path.parent)
        _write_atomic(file_path, new_content)


def apply_marker_block(content: str, marker_id: str, block_body: str, file_path: Path) -> str:
    begin, end = marker_bounds(file_path, marker_id)
    block = f"{begin}\n{block_body.rstrip()}\n{end}"
    pattern = re.compile(rf"{re.escape(begin)}.*?{re.escape(end)}", re.DOTALL)
    if pattern.search(content):
        return pattern.sub(block, content)
    if content.strip():
        return content.rstrip() + "\n\n" + block + "\n"
    return block + "\n"


def remove_marker_block(content: str, marker_id: str, file_path: Path) -> str:
    begin, end = marker_bounds(file_path, marker_id)
    pattern = re.compile(rf"{re.escape(begin)}.*?{re.escape(end)}\n?", re.DOTALL)
    cleaned = pattern.sub("", content)
    return cleaned.strip() + "\n" if cleaned.strip() else ""


def _extract_marker_block(content: str, marker_id: str, file_path: Path) -> str | None:
    begin, end = marker_bounds(file_path, marker_id)
    pattern = re.compile(rf"{re.escape(begin)}.*?{re.escape(end)}", re.DOTALL)
    match = pattern.search(content)
    return match.group(0) if match else None


def marker_bounds(file_path: Path, marker_id: str) -> tuple[str, str]:
    style = _marker_style_for_path(file_path)
    if style == "html":
        return f"<!-- BEGIN {marker_id} -->", f"<!-- END {marker_id} -->"
    if style == "slash":
        return f"// BEGIN {marker_id}", f"// END {marker_id}"
    if style == "block":
        return f"/* BEGIN {marker_id} */", f"/* END {marker_id} */"
    return f"# BEGIN {marker_id}", f"# END {marker_id}"


def _marker_style_for_path(file_path: Path) -> str:
    name = file_path.name.lower()
    ext = file_path.suffix.lower()
    if ext in {".md", ".mdc", ".markdown", ".mdx"}:
        return "html"
    if name.endswith(".env") or ext in {".env", ".sh", ".bash", ".zsh", ".fish", ".py", ".rb", ".pl", ".ps1"}:
        return "hash"
    if ext in {".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cc", ".cpp", ".go", ".rs"}:
        return "slash"
    if ext in {".css", ".scss", ".less"}:
        return "block"
    return "hash"


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


def _dump_structured(data: object, format: str) -> str:
    if format == "json":
        return json.dumps(data, indent=2)
    if format == "toml":
        return tomli_w.dumps(data if isinstance(data, dict) else {})
    if format == "yaml":
        return yaml.safe_dump(data, sort_keys=False).rstrip() + "\n"
    raise ValueError(f"Unsupported format: {format}")


def _serialize_value(value: object) -> str:
    try:
        return json.dumps(value, sort_keys=True)
    except TypeError:
        return yaml.safe_dump(value, sort_keys=False)



def _write_atomic(path: Path, content: str) -> None:
    tmp = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
