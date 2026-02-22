"""Environment variable interpolation utilities."""

from __future__ import annotations

import re

ENV_REF_RE = re.compile(r"\$(\w+)|\$\{([^}]+)\}")


def interpolate_env_refs(value: str, env_map: dict[str, str]) -> str:
    missing: list[str] = []

    def repl(match: re.Match[str]) -> str:
        name = match.group(1) or match.group(2) or ""
        if name in env_map:
            return env_map[name]
        missing.append(name)
        return match.group(0)

    out = ENV_REF_RE.sub(repl, value)
    if missing:
        names = ", ".join(sorted(set(missing)))
        raise RuntimeError(f"Missing environment values in injected env for: {names}")
    return out


def resolve_env_refs_in_obj(obj: object, env_map: dict[str, str]) -> object:
    if isinstance(obj, dict):
        return {k: resolve_env_refs_in_obj(v, env_map) for k, v in obj.items()}
    if isinstance(obj, list):
        return [resolve_env_refs_in_obj(v, env_map) for v in obj]
    if isinstance(obj, str):
        return interpolate_env_refs(obj, env_map)
    return obj
