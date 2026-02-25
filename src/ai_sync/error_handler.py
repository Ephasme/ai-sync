"""Friendly error reporting with structured log output."""

from __future__ import annotations

import datetime
import sys
import traceback
from pathlib import Path

from .display.base import Display

LOG_FILENAME = "ai-sync.errors.log"

_OP_NETWORK_HINTS = [
    "request library compatibility issue",
    "reqwest library",
    "TLS handshake timeout",
    "error sending request",
    "net/http:",
]

_OP_CHANNEL_HINTS = [
    "channel is closed",
    "Integrate with other apps",
]

_OP_DROPPED_HINTS = [
    "connection was unexpectedly dropped",
]

_OP_AUTH_HINTS = [
    "1Password auth required",
]


def _classify(exc: BaseException) -> tuple[str, str]:
    """Return (title, human-friendly message) for a known error pattern."""
    msg = str(exc)

    if any(h in msg for h in _OP_NETWORK_HINTS):
        return (
            "1Password network error",
            "Could not reach 1Password servers. This is usually a temporary issue — "
            "wait a moment and try again.\n\n"
            "If the problem persists, check that the 1Password desktop app can reach "
            "the internet and that no firewall or VPN is blocking outbound TLS.",
        )

    if any(h in msg for h in _OP_CHANNEL_HINTS):
        return (
            "1Password desktop app not connected",
            "The IPC channel to the 1Password desktop app is closed.\n\n"
            "Make sure 1Password is open, then go to:\n"
            "  Settings → Developer → Integrate with 1Password CLI\n"
            "and toggle it on.",
        )

    if any(h in msg for h in _OP_DROPPED_HINTS):
        return (
            "1Password desktop app disconnected",
            "The connection to the 1Password desktop app was unexpectedly dropped.\n\n"
            "Make sure 1Password is open and try again.",
        )

    if any(h in msg for h in _OP_AUTH_HINTS):
        return (
            "1Password not configured",
            "No 1Password account is configured.\n\n"
            "Run `ai-sync install` to set one up, or export OP_ACCOUNT before running.",
        )

    return ("Error", msg)


def write_error_log(
    exc: BaseException,
    log_path: Path,
    context: dict[str, str] | None = None,
) -> bool:
    """Append a structured entry to log_path. Returns True on success."""
    tb = traceback.format_exc()
    timestamp = datetime.datetime.now().isoformat(timespec="seconds")

    lines: list[str] = [
        f"[{timestamp}]  {type(exc).__name__}: {exc}",
    ]
    if context:
        for k, v in context.items():
            lines.append(f"  {k}: {v}")
    lines.append("")
    lines.append(tb.rstrip())
    lines.append("-" * 72)
    lines.append("")

    entry = "\n".join(lines) + "\n"

    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(entry)
        return True
    except OSError:
        return False


def handle_fatal(
    exc: BaseException,
    display: Display,
    log_path: Path,
    context: dict[str, str] | None = None,
) -> None:
    """Show a human-friendly panel and write full details to the error log."""
    title, friendly = _classify(exc)
    logged = write_error_log(exc, log_path, context)

    body = friendly
    if logged:
        body += f"\n\nFull details → {log_path}"

    try:
        display.panel(body, title=title, style="error")
    except Exception:
        print(f"\n{title}: {friendly}", file=sys.stderr)
        if logged:
            print(f"Full details → {log_path}", file=sys.stderr)
