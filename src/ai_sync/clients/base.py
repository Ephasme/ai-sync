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
