"""Adapter for structured-data path operations.

This module is the sole owner of path parsing, escaping, reading, writing,
and deleting within nested dict/list structures.  Every other module must go
through the public API here; the underlying path scheme (currently JSON Pointer
backed by the ``jsonpointer`` library) is an implementation detail that can be
swapped without touching callers.
"""

from __future__ import annotations

from jsonpointer import JsonPointer, JsonPointerException

# ---------------------------------------------------------------------------
# Path parsing / escaping
# ---------------------------------------------------------------------------


def split_path(path: str) -> list[str]:
    """Split a structured path into its component segments.

    ``"/"`` (root) and ``""`` both return an empty list.
    """
    if path == "" or path == "/":
        return []
    if not path.startswith("/"):
        raise ValueError(f"Invalid path: {path}")
    try:
        return list(JsonPointer(path).get_parts())
    except JsonPointerException as exc:
        raise ValueError(f"Invalid path: {path}") from exc


def escape_path_segment(segment: str) -> str:
    """Escape a single segment so it can be embedded in a path string."""
    raw = JsonPointer.from_parts([str(segment)]).path
    return raw[1:] if raw.startswith("/") else raw


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def get_at_path(data: object, path: str) -> object:
    """Return the value located at *path* inside *data*.

    Raises ``KeyError`` when the path does not exist.
    """
    if path == "/":
        return data
    parts = split_path(path)
    cur: object = data
    for part in parts:
        if isinstance(cur, dict):
            if part not in cur:
                raise KeyError(path)
            cur = cur[part]
        elif isinstance(cur, list):
            idx = int(part)
            if idx >= len(cur):
                raise KeyError(path)
            cur = cur[idx]
        else:
            raise KeyError(path)
    return cur


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


def set_at_path(data: object, path: str, value: object) -> object:
    """Set *value* at *path*, creating intermediate dicts as needed.

    When the next segment is numeric and the current container does not
    already exist as a list, a ``ValueError`` is raised rather than
    guessing the container type.

    Returns the (possibly replaced) root object.
    """
    if path == "/":
        return value
    parts = split_path(path)
    if not parts:
        return data
    cur: object = data
    for idx, part in enumerate(parts[:-1]):
        if isinstance(cur, list):
            list_idx = int(part)
            while len(cur) <= list_idx:
                cur.append({})
            if not isinstance(cur[list_idx], (dict, list)):
                cur[list_idx] = {}
            cur = cur[list_idx]
            continue
        if not isinstance(cur, dict):
            return data
        if part not in cur or not isinstance(cur[part], (dict, list)):
            next_part = parts[idx + 1]
            if next_part.isdigit():
                raise ValueError(
                    f"Ambiguous path {path!r}: "
                    f"list container is not explicitly defined at {part!r}"
                )
            cur[part] = {}
        cur = cur[part]
    last = parts[-1]
    if isinstance(cur, list):
        list_idx = int(last)
        while len(cur) <= list_idx:
            cur.append(None)
        cur[list_idx] = value
    elif isinstance(cur, dict):
        cur[last] = value
    return data


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


def delete_at_path(data: object, path: str) -> object:
    """Remove the value at *path*.

    * Root (``"/"``) → returns ``{}``.
    * List element → replaced with ``None`` (preserves indices).
    * Dict key → popped.

    Returns the (possibly replaced) root object.
    """
    if path == "/":
        return {}
    parts = split_path(path)
    if not parts:
        return data
    cur: object = data
    for idx, part in enumerate(parts[:-1]):
        if isinstance(cur, list):
            list_idx = int(part)
            while len(cur) <= list_idx:
                cur.append({})
            if not isinstance(cur[list_idx], (dict, list)):
                cur[list_idx] = {}
            cur = cur[list_idx]
            continue
        if not isinstance(cur, dict):
            return data
        if part not in cur or not isinstance(cur[part], (dict, list)):
            next_part = parts[idx + 1]
            if next_part.isdigit():
                raise ValueError(
                    f"Ambiguous path {path!r}: "
                    f"list container is not explicitly defined at {part!r}"
                )
            cur[part] = {}
        cur = cur[part]
    last = parts[-1]
    if isinstance(cur, list):
        list_idx = int(last)
        if list_idx < len(cur):
            cur[list_idx] = None
    elif isinstance(cur, dict):
        cur.pop(last, None)
    return data
