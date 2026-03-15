"""Persistence adapter for tracking ai-sync managed changes."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from ai_sync.data_classes.state_entry import StateEntry
from ai_sync.helpers import ensure_dir

__all__ = ["StateEntry", "StateStore"]

STATE_VERSION = 1


class StateStore:
    def __init__(self, project_root: Path) -> None:
        self._state_root = project_root / ".ai-sync" / "state"
        self._state_path = self._state_root / "state.json"
        self._blob_dir = self._state_root / "blobs"
        self._data: dict = {"version": STATE_VERSION, "entries": []}
        self._index: dict[str, dict] = {}

    def load(self) -> None:
        if not self._state_path.exists():
            return
        try:
            raw = self._state_path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(data, dict):
            return
        entries = data.get("entries")
        if not isinstance(entries, list):
            return
        self._data = {"version": data.get("version", STATE_VERSION), "entries": entries}
        self._index = {}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            key = self._make_key(entry.get("file_path"), entry.get("format"), entry.get("target"))
            if key:
                self._index[key] = entry

    def save(self) -> None:
        ensure_dir(self._state_root)
        self._write_atomic(self._state_path, json.dumps(self._data, indent=2))
        self._set_restrictive_permissions(self._state_path)

    def list_entries(self) -> list[dict]:
        return list(self._data.get("entries", []))

    def get_entry(self, file_path: Path, format: str, target: str) -> dict | None:
        key = self._make_key(str(file_path), format, target)
        if not key:
            return None
        return self._index.get(key)

    def ensure_entry(
        self,
        file_path: Path,
        format: str,
        target: str,
        *,
        kind: str | None = None,
        resource: str | None = None,
        name: str | None = None,
        description: str | None = None,
        source_alias: str | None = None,
    ) -> dict:
        key = self._make_key(str(file_path), format, target)
        if not key:
            raise ValueError("Invalid state entry key")
        entry = self._index.get(key)
        if entry is not None:
            if kind is not None:
                entry["kind"] = kind
            if resource is not None:
                entry["resource"] = resource
            if name is not None:
                entry["name"] = name
            if description is not None:
                entry["description"] = description
            if source_alias is not None:
                entry["source_alias"] = source_alias
            return entry
        entry = {
            "file_path": str(file_path),
            "format": format,
            "target": target,
            "baseline": {},
        }
        if kind is not None:
            entry["kind"] = kind
        if resource is not None:
            entry["resource"] = resource
        if name is not None:
            entry["name"] = name
        if description is not None:
            entry["description"] = description
        if source_alias is not None:
            entry["source_alias"] = source_alias
        self._data["entries"].append(entry)
        self._index[key] = entry
        return entry

    def record_baseline(
        self,
        file_path: Path,
        format: str,
        target: str,
        *,
        exists: bool,
        content: str | None,
        kind: str | None = None,
        resource: str | None = None,
        name: str | None = None,
        description: str | None = None,
        source_alias: str | None = None,
    ) -> None:
        entry = self.ensure_entry(
            file_path,
            format,
            target,
            kind=kind,
            resource=resource,
            name=name,
            description=description,
            source_alias=source_alias,
        )
        if entry.get("baseline"):
            return
        if not exists:
            entry["baseline"] = {"exists": False}
            return
        if content is None:
            entry["baseline"] = {"exists": True}
            return
        blob_id = self.store_blob(content)
        entry["baseline"] = {
            "exists": True,
            "blob_id": blob_id,
            "value_hash": self._hash_content(content),
        }

    def store_blob(self, content: str) -> str:
        ensure_dir(self._blob_dir)
        blob_id = self._hash_content(content)
        blob_path = self._blob_dir / blob_id
        if not blob_path.exists():
            self._write_atomic(blob_path, content)
            self._set_restrictive_permissions(blob_path)
        return blob_id

    def fetch_blob(self, blob_id: str) -> str | None:
        blob_path = self._blob_dir / blob_id
        if not blob_path.exists():
            return None
        try:
            return blob_path.read_text(encoding="utf-8")
        except OSError:
            return None

    def remove_entry(self, file_path: Path, format: str, target: str) -> None:
        key = self._make_key(str(file_path), format, target)
        if not key:
            return
        self._index.pop(key, None)
        entries = self._data.get("entries", [])
        self._data["entries"] = [
            entry
            for entry in entries
            if self._make_key(entry.get("file_path"), entry.get("format"), entry.get("target")) != key
        ]

    def delete_state(self) -> None:
        if not self._state_root.exists():
            return
        for path in sorted(self._state_root.rglob("*"), reverse=True):
            try:
                if path.is_file() or path.is_symlink():
                    path.unlink(missing_ok=True)
                elif path.is_dir():
                    path.rmdir()
            except OSError:
                continue
        try:
            self._state_root.rmdir()
        except OSError:
            pass

    @staticmethod
    def _hash_content(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _make_key(file_path: object, format: object, target: object) -> str | None:
        if not isinstance(file_path, str) or not isinstance(format, str) or not isinstance(target, str):
            return None
        return f"{file_path}::{format}::{target}"

    @staticmethod
    def _write_atomic(path: Path, content: str) -> None:
        tmp = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as file_obj:
                file_obj.write(content)
            tmp.replace(path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    @staticmethod
    def _set_restrictive_permissions(path: Path) -> None:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
