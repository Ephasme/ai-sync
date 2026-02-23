"""Precedence and override handling."""

from __future__ import annotations

import json
import re
from typing import Sequence

FORBIDDEN_PTR_SEGMENT_RE = re.compile(r"auth|oauth|token|secret|password|api_key", re.IGNORECASE)


def parse_override(item: str, *, parse_json: bool) -> tuple[str, object]:
    if "=" not in item:
        raise RuntimeError(f"Invalid override token {item!r}, expected <pointer>=<value>")
    pointer, raw_value = item.split("=", 1)
    if not pointer or not pointer.startswith("/"):
        raise RuntimeError(f"Invalid JSON pointer {pointer!r}")
    if any(FORBIDDEN_PTR_SEGMENT_RE.search(seg) for seg in pointer.split("/")[1:]):
        raise RuntimeError(f"Override to forbidden secret-like path is not allowed: {pointer}")
    if parse_json:
        try:
            return pointer, json.loads(raw_value)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid JSON override for {pointer}: {exc}") from exc
    return pointer, raw_value


def _decode_pointer_segment(segment: str) -> str:
    return segment.replace("~1", "/").replace("~0", "~")


def apply_overrides(document: dict, overrides: Sequence[tuple[str, object]]) -> dict:
    out = json.loads(json.dumps(document))
    for pointer, value in overrides:
        parts = [_decode_pointer_segment(p) for p in pointer.split("/")[1:]]
        if not parts:
            raise RuntimeError("Root override is not allowed")
        cur: object = out
        for p in parts[:-1]:
            if not isinstance(cur, dict) or p not in cur:
                raise RuntimeError(f"Unknown override path: {pointer}")
            cur = cur[p]
        leaf = parts[-1]
        if not isinstance(cur, dict) or leaf not in cur:
            raise RuntimeError(f"Unknown override leaf path: {pointer}")
        if isinstance(cur[leaf], (dict, list)):
            raise RuntimeError(f"Override must target leaf value, got container at: {pointer}")
        cur[leaf] = value
    return out
