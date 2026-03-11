"""1Password integration for resolving op:// references in env templates."""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
from pathlib import Path

from onepassword.client import Client
from onepassword.defaults import DesktopAuth

from ai_sync.config_store import resolve_op_account_identifier

ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
OP_REF_PREFIX = "op://"


def parse_injected_env(content: str) -> dict[str, str]:
    env: dict[str, str] = {}
    for idx, raw in enumerate(content.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise RuntimeError(f"Invalid env line {idx}: expected NAME=VALUE format")
        name, value = line.split("=", 1)
        key = name.strip()
        if not ENV_NAME_RE.match(key):
            raise RuntimeError(f"Invalid env variable name at line {idx}: {key!r}")
        env[key] = value
    return env


def _extract_op_refs(lines: list[str]) -> tuple[list[str], dict[int, str]]:
    """Extract unique op:// refs from lines. Returns (refs, line_idx -> ref)."""
    refs: list[str] = []
    seen: set[str] = set()
    line_to_ref: dict[int, str] = {}
    for idx, line in enumerate(lines):
        if "=" not in line or line.strip().startswith("#"):
            continue
        _, value = line.split("=", 1)
        val = value.strip()
        if val.startswith(OP_REF_PREFIX):
            ref = val
            line_to_ref[idx] = ref
            if ref not in seen:
                seen.add(ref)
                refs.append(ref)
    return refs, line_to_ref


def _inject_resolved(lines: list[str], line_to_ref: dict[int, str], resolved: dict[str, str]) -> str:
    """Replace op:// refs in lines with resolved values."""
    out: list[str] = []
    for idx, line in enumerate(lines):
        if idx in line_to_ref:
            ref = line_to_ref[idx]
            name = line.split("=", 1)[0].strip()
            out.append(f"{name}={resolved.get(ref, ref)}")
        else:
            out.append(line)
    return "\n".join(out)


def _format_cli_error(message: str) -> str:
    if "multiple accounts found" in message:
        return (
            "1Password CLI could not choose an account. Set OP_ACCOUNT to the sign-in address "
            "or user ID from `op account list`, or rerun "
            "`ai-sync install --op-account-identifier example.1password.com`."
        )
    if "found no accounts for filter" in message:
        return (
            "Configured OP_ACCOUNT does not match a 1Password CLI sign-in address or user ID. "
            "Use `op account list` to find the correct value."
        )
    return message.strip() or "1Password CLI failed to resolve secret references."


def _resolve_cli_env(config_root: Path | None) -> dict[str, str]:
    token = os.getenv("OP_SERVICE_ACCOUNT_TOKEN")
    if token:
        return {"OP_SERVICE_ACCOUNT_TOKEN": token}

    account = os.getenv("OP_ACCOUNT") or resolve_op_account_identifier(config_root)
    if account:
        return {"OP_ACCOUNT": account}

    raise RuntimeError(
        "1Password auth required. Run `ai-sync install` or set OP_SERVICE_ACCOUNT_TOKEN/OP_ACCOUNT."
    )


def _load_runtime_env_with_cli(env_template_path: Path, config_root: Path | None) -> dict[str, str]:
    env = os.environ.copy()
    env.update(_resolve_cli_env(config_root))
    try:
        result = subprocess.run(
            ["op", "inject", "--in-file", str(env_template_path)],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("1Password CLI is not installed or `op` is not on PATH.") from exc
    except subprocess.CalledProcessError as exc:
        msg = exc.stderr or exc.stdout or str(exc)
        raise RuntimeError(_format_cli_error(msg)) from exc
    return parse_injected_env(result.stdout)


def _resolve_auth(config_root: Path | None) -> str | DesktopAuth:
    token = os.getenv("OP_SERVICE_ACCOUNT_TOKEN")
    account = os.getenv("OP_ACCOUNT") or resolve_op_account_identifier(config_root)
    if token:
        return token
    if account:
        return DesktopAuth(account_name=account)
    raise RuntimeError(
        "1Password auth required. Run `ai-sync install` or set OP_SERVICE_ACCOUNT_TOKEN/OP_ACCOUNT."
    )


async def _load_runtime_env_async(env_template_path: Path, config_root: Path | None) -> dict[str, str]:
    content = env_template_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    refs, line_to_ref = _extract_op_refs(lines)
    if not refs:
        return parse_injected_env(content)

    auth = _resolve_auth(config_root)

    client = await Client.authenticate(
        auth=auth,
        integration_name="ai-sync",
        integration_version="0.1.0",
    )
    response = await client.secrets.resolve_all(refs)

    resolved: dict[str, str] = {}
    for ref, resp in response.individual_responses.items():
        if resp.error is not None:
            msg = str(resp.error)
            raise RuntimeError(f"Failed to resolve {ref}: {msg}")
        if resp.content:
            resolved[ref] = resp.content.secret

    injected = _inject_resolved(lines, line_to_ref, resolved)
    return parse_injected_env(injected)


def load_runtime_env_from_op(env_template_path: Path, config_root: Path | None = None) -> dict[str, str]:
    if not env_template_path.exists():
        return {}
    content = env_template_path.read_text(encoding="utf-8")
    refs, _line_to_ref = _extract_op_refs(content.splitlines())
    if not refs:
        return parse_injected_env(content)

    cli_error: Exception | None = None
    try:
        return _load_runtime_env_with_cli(env_template_path, config_root)
    except Exception as exc:
        cli_error = exc

    try:
        return asyncio.run(_load_runtime_env_async(env_template_path, config_root))
    except Exception as sdk_error:
        raise RuntimeError(
            "Failed to resolve 1Password references.\n"
            f"CLI: {cli_error}\n"
            f"SDK: {sdk_error}"
        ) from sdk_error
