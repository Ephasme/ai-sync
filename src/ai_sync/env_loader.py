"""Environment variable interpolation utilities."""

from __future__ import annotations

import re

ENV_REF_RE = re.compile(r"\$(\w+)|\$\{([^}]+)\}")
_ESCAPE_SENTINEL = "\x00"


def interpolate_env_refs(value: str, env_map: dict[str, str]) -> str:
    escaped = value.replace("$$", _ESCAPE_SENTINEL)

    missing: list[str] = []

    def repl(match: re.Match[str]) -> str:
        name = match.group(1) or match.group(2) or ""
        if name in env_map:
            return env_map[name]
        missing.append(name)
        return match.group(0)

    out = ENV_REF_RE.sub(repl, escaped)
    if missing:
        names = ", ".join(sorted(set(missing)))
        raise RuntimeError(f"Missing environment values in injected env for: {names}")
    return out.replace(_ESCAPE_SENTINEL, "$")


def collect_env_refs(obj: object) -> set[str]:
    """Return all ``${VAR}`` / ``$VAR`` names referenced in a nested structure."""
    refs: set[str] = set()

    def _walk(node: object) -> None:
        if isinstance(node, dict):
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for v in node:
                _walk(v)
        elif isinstance(node, str):
            cleaned = node.replace("$$", "")
            for m in ENV_REF_RE.finditer(cleaned):
                refs.add(m.group(1) or m.group(2) or "")

    _walk(obj)
    return refs


def resolve_env_refs_in_obj(obj: object, env_map: dict[str, str]) -> object:
    if isinstance(obj, dict):
        return {k: resolve_env_refs_in_obj(v, env_map) for k, v in obj.items()}
    if isinstance(obj, list):
        return [resolve_env_refs_in_obj(v, env_map) for v in obj]
    if isinstance(obj, str):
        return interpolate_env_refs(obj, env_map)
    return obj
