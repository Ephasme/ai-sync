"""Abstract client adapter and shared helpers."""

from __future__ import annotations

import json
import os
import stat
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path

import tomli
import tomli_w

class Client(ABC):
    _MANAGED_MARKER = "_managed_by_sync_ai_configs"  # Migration: read from existing config when sidecar missing
    _SIDECAR_NAME = ".sync_managed_mcp.json"

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    @abstractmethod
    def config_dir(self) -> Path:
        ...

    def get_agents_dir(self) -> Path:
        return self.config_dir / "agents"

    def get_skills_dir(self) -> Path:
        return self.config_dir / "skills"

    @staticmethod
    def _read_json_config(path: Path) -> dict:
        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    @staticmethod
    def _read_toml_config(path: Path) -> dict:
        if not path.exists():
            return {}
        try:
            with open(path, "rb") as f:
                return tomli.load(f)
        except (OSError, tomli.TOMLDecodeError):
            return {}

    @staticmethod
    def _write_json_config(data: dict) -> str:
        return json.dumps(data, indent=2)

    @staticmethod
    def _write_toml_config(data: dict) -> str:
        return tomli_w.dumps(data)

    def _build_mcp_env(self, server: dict, secret_srv: dict) -> dict:
        env_parts: list[dict] = []
        if server.get("env"):
            env_parts.append({k: str(v) if v is not None else "" for k, v in server["env"].items()})
        if secret_srv.get("env"):
            env_parts.append({k: str(v) if v is not None else "" for k, v in secret_srv["env"].items()})
        if not env_parts:
            return {}
        merged: dict = {}
        for e in env_parts:
            merged.update(e)
        return merged

    def _get_secret_for_server(self, server_id: str, secrets: dict) -> dict:
        return secrets.get("servers", {}).get(server_id, {})

    def _get_managed_mcp_sidecar_path(self) -> Path:
        return self.config_dir / self._SIDECAR_NAME

    def _read_managed_mcp_ids(self) -> set[str]:
        path = self._get_managed_mcp_sidecar_path()
        if not path.exists():
            return set()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            ids = data if isinstance(data, list) else data.get("managed", [])
            return set(str(i) for i in ids)
        except (json.JSONDecodeError, OSError):
            return set()

    def _write_managed_mcp_ids(self, server_ids: list[str]) -> None:
        path = self._get_managed_mcp_sidecar_path()
        path.write_text(json.dumps(server_ids, indent=2), encoding="utf-8")

    def _merge_managed_servers(self, existing_servers: dict, new_servers: dict) -> dict:
        managed_ids = self._read_managed_mcp_ids()
        if not managed_ids:
            managed_ids = {
                sid
                for sid, srv in existing_servers.items()
                if srv.get(self._MANAGED_MARKER)
            }
        merged: dict = {}
        for sid, srv in existing_servers.items():
            if sid in managed_ids and sid not in new_servers:
                continue
            cleaned = {k: v for k, v in srv.items() if k != self._MANAGED_MARKER}
            merged[sid] = cleaned
        for sid, entry in new_servers.items():
            merged[sid] = dict(entry)
        self._write_managed_mcp_ids(list(new_servers.keys()))
        return merged

    @staticmethod
    def _set_restrictive_permissions(path: Path) -> None:
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError as exc:
            print(f"  Warning: Could not set restrictive permissions on {path}: {exc}")

    @staticmethod
    def _warn_plaintext_secrets(path: Path) -> None:
        print(f"  Warning: Secrets written in plaintext to {path}. Consider using a secrets manager.")

    @abstractmethod
    def write_agent(self, slug: str, meta: dict, raw_content: str, prompt_src_path: Path) -> None:
        ...

    @abstractmethod
    def sync_mcp(self, servers: dict, secrets: dict, for_client: Callable[[dict, str], bool]) -> None:
        ...

    @abstractmethod
    def sync_client_config(self, settings: dict) -> None:
        ...

    def enable_subagents_fallback(self) -> None:
        pass

    def sync_mcp_instructions(self, instructions: str) -> None:
        pass
