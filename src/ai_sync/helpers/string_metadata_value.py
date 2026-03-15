"""Normalize optional string metadata values."""

from __future__ import annotations


def string_metadata_value(value: object, fallback: str) -> str:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped
    return fallback
