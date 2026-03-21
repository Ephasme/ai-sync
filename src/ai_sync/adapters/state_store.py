"""Persistence adapter for tracking ai-sync managed changes."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from ai_sync.data_classes.state_entry import StateEntry
from ai_sync.helpers import ensure_dir

__all__ = ["StateEntry", "StateStore"]

STATE_VERSION = 2


class IncompatibleStateError(RuntimeError):
    """Raised when persisted state version is incompatible with the running pipeline."""


class StateStore:
    def __init__(self, project_root: Path) -> None:
        self._state_root = project_root / ".ai-sync" / "state"
        self._state_path = self._state_root / "state.json"
        self._blob_dir = self._state_root / "blobs"
        self._data: dict = {"version": STATE_VERSION, "entries": [], "effects": []}
        self._index: dict[str, dict] = {}
        self._effect_index: dict[str, dict] = {}
        self._loaded_version: int = STATE_VERSION

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
        self._loaded_version = data.get("version", 1)
        entries = data.get("entries")
        if not isinstance(entries, list):
            entries = []
        effects = data.get("effects")
        if not isinstance(effects, list):
            effects = []
        self._data = {"version": STATE_VERSION, "entries": entries, "effects": effects}
        self._index = {}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            key = self._make_key(entry.get("file_path"), entry.get("format"), entry.get("target"))
            if key:
                self._index[key] = entry
        self._effect_index = {}
        for effect in effects:
            if not isinstance(effect, dict):
                continue
            ekey = self._make_effect_key(effect.get("effect_type"), effect.get("target_key"))
            if ekey:
                self._effect_index[ekey] = effect

    def check_version(self) -> None:
        """Raise IncompatibleStateError when the persisted state predates this pipeline."""
        if self._loaded_version != STATE_VERSION:
            raise IncompatibleStateError(
                f"Persisted state version {self._loaded_version} is incompatible with "
                f"the current pipeline (version {STATE_VERSION}). "
                "Run `ai-sync uninstall --apply` to clean up old managed state, "
                "then reapply with `ai-sync apply`."
            )

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

    # ------------------------------------------------------------------
    # Effect tracking
    # ------------------------------------------------------------------

    def list_effects(self) -> list[dict]:
        return list(self._data.get("effects", []))

    def get_effect(self, effect_type: str, target_key: str) -> dict | None:
        ekey = self._make_effect_key(effect_type, target_key)
        if not ekey:
            return None
        return self._effect_index.get(ekey)

    def record_effect(
        self,
        *,
        effect_type: str,
        target: str,
        target_key: str,
        baseline: dict,
    ) -> None:
        """Record an effect baseline, only if not already tracked."""
        ekey = self._make_effect_key(effect_type, target_key)
        if not ekey:
            raise ValueError("Invalid effect key")
        if ekey in self._effect_index:
            return
        entry = {
            "effect_type": effect_type,
            "target": target,
            "target_key": target_key,
            "baseline": baseline,
        }
        self._data["effects"].append(entry)
        self._effect_index[ekey] = entry

    def remove_effect(self, effect_type: str, target_key: str) -> None:
        ekey = self._make_effect_key(effect_type, target_key)
        if not ekey:
            return
        self._effect_index.pop(ekey, None)
        effects = self._data.get("effects", [])
        self._data["effects"] = [
            e
            for e in effects
            if self._make_effect_key(e.get("effect_type"), e.get("target_key")) != ekey
        ]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

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
    def _make_effect_key(effect_type: object, target_key: object) -> str | None:
        if not isinstance(effect_type, str) or not isinstance(target_key, str):
            return None
        return f"{effect_type}::{target_key}"

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
