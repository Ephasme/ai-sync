"""Shared helper utilities for ai_sync."""

from __future__ import annotations

import filecmp
import os
import re
import shutil
from contextlib import contextmanager
from pathlib import Path


def to_kebab_case(name: str) -> str:
    return re.sub(r"[_ ]+", "-", name).lower()


def validate_client_settings(settings: object) -> list[str]:
    if settings is None:
        return []
    if not isinstance(settings, dict):
        return ["Client settings must be a mapping."]
    errors: list[str] = []
    allowed_top = {"experimental", "subagents", "mode", "tools"}
    unknown_top = sorted(set(settings) - allowed_top)
    if unknown_top:
        errors.append(f"Unknown client setting(s): {', '.join(unknown_top)}")
    if "experimental" in settings and not isinstance(settings["experimental"], bool):
        errors.append("experimental must be true/false")
    if "subagents" in settings and not isinstance(settings["subagents"], bool):
        errors.append("subagents must be true/false")
    if "mode" in settings:
        val = settings.get("mode")
        if val not in (None, "", "strict", "normal", "yolo"):
            errors.append(f"Invalid mode: {val!r}")
    tools = settings.get("tools")
    if tools is not None:
        if not isinstance(tools, dict):
            errors.append("tools must be a mapping")
        else:
            unknown_tools = sorted(set(tools) - {"sandbox"})
            if unknown_tools:
                errors.append(f"Unknown tools setting(s): {', '.join(unknown_tools)}")
            if "sandbox" in tools and not isinstance(tools["sandbox"], bool):
                errors.append("tools.sandbox must be true/false")
    return errors


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


@contextmanager
def _atomic_write(path: Path):
    tmp = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            yield f
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def write_content_if_different(path: Path, content: str) -> bool:
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                if f.read() == content:
                    return False
        except (OSError, UnicodeDecodeError) as exc:
            print(f"  Warning: Could not read {path}, skipping: {exc}")
            return False
    ensure_dir(path.parent)
    with _atomic_write(path) as f:
        f.write(content)
    return True


def deep_merge(base: dict, overlay: dict) -> dict:
    result: dict = {}
    for k, v in base.items():
        result[k] = dict(v) if isinstance(v, dict) else v
    for k, v in overlay.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def copy_file_if_different(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    if dst.exists() and filecmp.cmp(src, dst, shallow=False):
        return False
    ensure_dir(dst.parent)
    tmp = dst.with_suffix(f"{dst.suffix}.{os.getpid()}.tmp")
    try:
        shutil.copy2(src, tmp)
        tmp.replace(dst)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return True


def sync_tree_if_different(src: Path, dst: Path, skip_patterns: set[str]) -> bool:
    changed = False

    def should_skip(relative_path: Path) -> bool:
        return any(part in skip_patterns for part in relative_path.parts)

    for item in src.rglob("*"):
        rel = item.relative_to(src)
        if item.is_file() and not should_skip(rel):
            target = dst / rel
            if not target.exists() or not filecmp.cmp(item, target, shallow=False):
                ensure_dir(target.parent)
                tmp = target.with_suffix(f"{target.suffix}.{os.getpid()}.tmp")
                try:
                    shutil.copy2(item, tmp)
                    tmp.replace(target)
                except BaseException:
                    tmp.unlink(missing_ok=True)
                    raise
                changed = True
    return changed


def extract_description(content: str) -> str:
    match = re.search(r"## Task\s+(.*)", content, re.IGNORECASE | re.DOTALL)
    if match:
        desc = match.group(1).strip().split("\n")[0]
        return desc[:150] + "..." if len(desc) > 150 else desc
    for line in content.splitlines():
        if line.strip() and not line.startswith("#"):
            return line.strip()[:100]
    return "AI Agent"


def validate_servers_yaml(data: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["mcp-servers.yaml root must be a mapping"]
    servers = data.get("servers")
    if servers is not None and not isinstance(servers, dict):
        errors.append("'servers' must be a mapping")
        return errors
    for sid, srv in (servers or {}).items():
        if not isinstance(srv, dict):
            errors.append(f"Server '{sid}' must be a mapping")
            continue
        if "method" in srv and srv["method"] not in ("stdio", "http", "sse"):
            errors.append(
                f"Server '{sid}': invalid method '{srv['method']}' (expected stdio/http/sse)"
            )
        if "timeout" in srv:
            errors.append(
                f"Server '{sid}': 'timeout' is no longer supported; use 'timeout_seconds'"
            )
        clients = srv.get("clients")
        if clients is not None and not isinstance(clients, list):
            errors.append(f"Server '{sid}': 'clients' must be a list, got {type(clients).__name__}")
        elif isinstance(clients, list):
            for c in clients:
                if not isinstance(c, str):
                    errors.append(
                        f"Server '{sid}': client entries must be strings, got {type(c).__name__}"
                    )
        if srv.get("method", "stdio") == "stdio" and not srv.get("command"):
            errors.append(f"Server '{sid}': stdio server must have a 'command'")
        if "timeout_seconds" in srv:
            timeout_seconds = srv.get("timeout_seconds")
            if not isinstance(timeout_seconds, (int, float)):
                errors.append(
                    f"Server '{sid}': 'timeout_seconds' must be a number, got {type(timeout_seconds).__name__}"
                )
            elif timeout_seconds < 0:
                errors.append(f"Server '{sid}': 'timeout_seconds' must be >= 0")
    return errors
