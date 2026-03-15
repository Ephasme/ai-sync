#!/usr/bin/env python3
"""Split inline prompt bundles into artifact.yaml + prompt.md."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

BUNDLE_PROMPT_FILENAME = "prompt.md"
PROMPT_BUNDLE_KINDS = ("prompts", "commands", "rules", "skills")
ORDERED_KEYS: dict[str, tuple[str, ...]] = {
    "prompts": ("slug", "name", "description"),
    "commands": ("description",),
    "rules": ("description", "alwaysApply", "globs"),
    "skills": ("name", "description"),
}


def _load_yaml_mapping(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise RuntimeError(f"{path} must contain a YAML mapping")
    return data


def _ordered_metadata(kind: str, data: dict) -> dict:
    ordered: dict[str, object] = {}
    for key in ORDERED_KEYS.get(kind, ()):
        if key in data and data[key] is not None:
            ordered[key] = data[key]
    for key, value in data.items():
        if key not in ordered and value is not None:
            ordered[key] = value
    return ordered


def _dump_yaml_mapping(data: dict) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def _migrate_bundle(repo_root: Path, kind: str, artifact_path: Path) -> bool:
    prompt_path = artifact_path.with_name(BUNDLE_PROMPT_FILENAME)
    data = _load_yaml_mapping(artifact_path)

    if "prompt" not in data:
        if prompt_path.exists():
            return False
        raise RuntimeError(
            f"{artifact_path.relative_to(repo_root)} has no inline prompt and no {BUNDLE_PROMPT_FILENAME}"
        )

    prompt = data.pop("prompt")
    if not isinstance(prompt, str):
        raise RuntimeError(f"{artifact_path.relative_to(repo_root)} must contain a string prompt")
    if prompt_path.exists():
        raise RuntimeError(
            f"Refusing to overwrite existing prompt file: {prompt_path.relative_to(repo_root)}"
        )

    artifact_path.write_text(_dump_yaml_mapping(_ordered_metadata(kind, data)), encoding="utf-8")
    prompt_path.write_text(prompt, encoding="utf-8")
    print(
        "migrated",
        artifact_path.relative_to(repo_root),
        "->",
        prompt_path.relative_to(repo_root),
    )
    return True


def _migrate_kind(repo_root: Path, kind: str) -> int:
    root = repo_root / kind
    if not root.is_dir():
        return 0

    migrated = 0
    for artifact_path in sorted(root.rglob("artifact.yaml")):
        if _migrate_bundle(repo_root, kind, artifact_path):
            migrated += 1
    return migrated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo_root", type=Path, help="Repository root to migrate")
    parser.add_argument(
        "--kind",
        dest="kinds",
        choices=PROMPT_BUNDLE_KINDS,
        nargs="+",
        default=list(PROMPT_BUNDLE_KINDS),
        help="Prompt-bearing bundle kinds to migrate (default: all)",
    )
    args = parser.parse_args()

    repo_root = args.repo_root.expanduser().resolve()
    migrated = 0
    for kind in args.kinds:
        migrated += _migrate_kind(repo_root, kind)
    print(f"prompt bundles migrated: {migrated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
