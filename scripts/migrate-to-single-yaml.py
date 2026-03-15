#!/usr/bin/env python3
"""Legacy shim for the split prompt-bundle migration."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    target = (
        Path(__file__).resolve().parent.parent
        / "migration"
        / "scripts"
        / "migrate_to_split_prompt_bundles.py"
    )
    os.execv(sys.executable, [sys.executable, str(target), *sys.argv[1:]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
