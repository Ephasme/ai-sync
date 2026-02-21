#!/usr/bin/env python3
"""Capture and verify client versions for sync guardrails."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


CLIENT_COMMANDS: dict[str, list[str]] = {
    "codex": ["codex", "--version"],
    "cursor": ["cursor", "--version"],
    "gemini": ["gemini", "--version"],
}

VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")


@dataclass(frozen=True)
class Version:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, text: str) -> "Version | None":
        match = VERSION_RE.search(text)
        if not match:
            return None
        return cls(int(match.group(1)), int(match.group(2)), int(match.group(3)))

    def as_tuple(self) -> tuple[int, int, int]:
        return (self.major, self.minor, self.patch)

    def major_minor(self) -> tuple[int, int]:
        return (self.major, self.minor)

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


def _run(cmd: list[str]) -> str:
    try:
        proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
        return (proc.stdout or "") + (proc.stderr or "")
    except FileNotFoundError:
        return ""
    except subprocess.CalledProcessError as exc:
        return (exc.stdout or "") + (exc.stderr or "")


def load_versions(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}


def check_versions(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, f"Missing version lock file: {path}. Run scripts/auto-sync/install_auto_sync.sh"

    expected = load_versions(path)
    if not expected:
        return False, f"No versions stored in {path}. Run scripts/auto-sync/install_auto_sync.sh"

    current: dict[str, str] = {}
    for name, cmd in CLIENT_COMMANDS.items():
        cmd_path = shutil.which(cmd[0])
        if not cmd_path:
            continue
        output = _run([cmd_path, *cmd[1:]])
        if not output.strip():
            continue
        parsed = Version.parse(output)
        if parsed is None:
            continue
        current[name] = str(parsed)
    for client, expected_version in expected.items():
        if client not in CLIENT_COMMANDS:
            return False, f"Unknown client in lock file: {client}"
        if client not in current:
            return False, f"Unable to detect {client} version (command missing or unreadable)"
        exp = Version.parse(expected_version)
        cur = Version.parse(current[client])
        if exp is None or cur is None:
            return False, f"Invalid version for {client} (expected {expected_version}, got {current[client]})"
        if exp.major_minor() != cur.major_minor():
            return False, f"Version mismatch: {client} expected {exp.major}.{exp.minor}.x got {cur}"
    return True, "OK"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", type=Path, help="Check current versions against file")
    args = parser.parse_args()

    if args.check:
        ok, msg = check_versions(args.check)
        if ok:
            print("OK")
            return 0
        print(msg)
        return 4

    print("Specify --check", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
