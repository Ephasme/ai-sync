"""State store for tracking ai-sync managed changes."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from .helpers import ensure_dir


STATE_VERSION = 1


@dataclass
class StateEntry:
    file_path: str
    format: str
    target: str
    baseline: dict


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

    def list_targets(self, file_path: Path, format: str, prefix: str) -> list[str]:
        out: list[str] = []
        for entry in self._data.get("entries", []):
            if entry.get("file_path") != str(file_path):
                continue
            if entry.get("format") != format:
                continue
            target = entry.get("target")
            if isinstance(target, str) and target.startswith(prefix):
                out.append(target)
        return out

    def get_entry(self, file_path: Path, format: str, target: str) -> dict | None:
        key = self._make_key(str(file_path), format, target)
        if not key:
            return None
        return self._index.get(key)

    def ensure_entry(self, file_path: Path, format: str, target: str) -> dict:
        key = self._make_key(str(file_path), format, target)
        if not key:
            raise ValueError("Invalid state entry key")
        entry = self._index.get(key)
        if entry is not None:
            return entry
        entry = {
            "file_path": str(file_path),
            "format": format,
            "target": target,
            "baseline": {},
        }
        self._data["entries"].append(entry)
        self._index[key] = entry
        return entry

    def record_baseline(self, file_path: Path, format: str, target: str, *, exists: bool, content: str | None) -> None:
        entry = self.ensure_entry(file_path, format, target)
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
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(content)
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
