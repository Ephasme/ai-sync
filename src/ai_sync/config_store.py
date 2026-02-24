"""Config storage for ai-sync."""

from __future__ import annotations

import os
from pathlib import Path

import tomli as tomllib

import tomli_w


DEFAULT_SECRET_PROVIDER = "1password"
CONFIG_FILE_NAME = "config.toml"


def get_config_root() -> Path:
    return Path.home() / ".ai-sync"


def get_config_path(config_root: Path | None = None) -> Path:
    root = config_root or get_config_root()
    return root / CONFIG_FILE_NAME


def ensure_layout(config_root: Path | None = None) -> Path:
    root = config_root or get_config_root()
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "prompts").mkdir(parents=True, exist_ok=True)
    (root / "config" / "skills").mkdir(parents=True, exist_ok=True)
    (root / "config" / "commands").mkdir(parents=True, exist_ok=True)
    (root / "cache").mkdir(parents=True, exist_ok=True)
    return root


def load_config(config_root: Path | None = None) -> dict:
    path = get_config_path(config_root)
    if not path.exists():
        raise RuntimeError(f"Missing config file: {path}")
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except OSError as exc:
        raise RuntimeError(f"Failed to read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"Invalid config file: {path}")
    return data


def write_config(data: dict, config_root: Path | None = None) -> Path:
    root = ensure_layout(config_root)
    path = get_config_path(root)
    try:
        path.write_text(tomli_w.dumps(data), encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"Failed to write {path}: {exc}") from exc
    return path


def resolve_op_account(config_root: Path | None = None) -> str | None:
    env_account = os.environ.get("OP_ACCOUNT")
    if env_account:
        return env_account
    try:
        config = load_config(config_root)
    except RuntimeError:
        return None
    value = config.get("op_account")
    return str(value) if value else None
