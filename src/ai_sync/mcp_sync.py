"""MCP resolution helpers."""

from __future__ import annotations


def resolve_servers_for_client(servers: dict, client_name: str) -> dict:
    resolved = {}
    for sid, srv in servers.items():
        base = {k: v for k, v in srv.items() if k != "client_overrides"}
        override = (srv.get("client_overrides") or {}).get(client_name, {})
        if override:
            merged = {**base}
            for key, val in override.items():
                if val is None:
                    continue
                if key in ("env", "headers", "auth") and isinstance(val, dict):
                    merged[key] = {**(base.get(key) or {}), **val}
                elif key == "oauth" and isinstance(val, dict):
                    filtered_val = {k: v for k, v in val.items() if v is not None}
                    merged[key] = {**(base.get("oauth") or {}), **filtered_val}
                else:
                    merged[key] = val
            resolved[sid] = merged
        else:
            resolved[sid] = base
    return resolved
