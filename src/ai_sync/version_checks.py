"""Client version detection and checks."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")
DEFAULT_VERSIONS_PATH = Path(__file__).with_name(".client-versions.json")


def run_command_capture_output(cmd: list[str]) -> str:
    try:
        proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
        return (proc.stdout or "") + (proc.stderr or "")
    except FileNotFoundError:
        return ""
    except subprocess.CalledProcessError as exc:
        return (exc.stdout or "") + (exc.stderr or "")


def detect_client_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    commands = {"codex": ["codex", "--version"], "cursor": ["cursor", "--version"], "gemini": ["gemini", "--version"]}
    augmented_path = os.environ.get("PATH", "")
    for extra in ["/opt/homebrew/bin", "/usr/local/bin"]:
        if extra not in augmented_path.split(":"):
            augmented_path = f"{extra}:{augmented_path}" if augmented_path else extra
    for name, cmd in commands.items():
        cmd_path = shutil.which(cmd[0], path=augmented_path)
        if not cmd_path:
            continue
        output = run_command_capture_output([cmd_path, *cmd[1:]])
        match = VERSION_RE.search(output)
        if match:
            versions[name] = f"{match.group(1)}.{match.group(2)}.{match.group(3)}"
    return versions


def get_default_versions_path() -> Path:
    return DEFAULT_VERSIONS_PATH


def check_client_versions(versions_path: Path) -> tuple[bool, str]:
    if not versions_path.exists():
        return False, f"Missing version lock file: {versions_path}."
    try:
        expected = json.loads(versions_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"Failed to read {versions_path}: {exc}"
    if not isinstance(expected, dict) or not expected:
        return False, f"No versions stored in {versions_path}"

    current = detect_client_versions()
    if not current:
        return False, "No client versions detected; ensure clients are installed and on PATH"

    for client, expected_version in expected.items():
        if client not in current:
            return False, f"Unable to detect {client} version"
        exp = VERSION_RE.search(str(expected_version))
        cur = VERSION_RE.search(str(current[client]))
        if not exp or not cur:
            return False, f"Invalid version for {client} (expected {expected_version}, got {current[client]})"
        if exp.group(1, 2) != cur.group(1, 2):
            return (
                True,
                f"Version mismatch: {client} expected {exp.group(1)}.{exp.group(2)}.x got {current[client]}",
            )
    return True, "OK"
