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


def resolve_op_refs(values: dict[str, str], config_root: Path | None = None) -> dict[str, str]:
    """Resolve a pre-parsed {name: value_or_op_ref} dict.

    Plain values are returned as-is.  ``op://`` references are resolved
    via the 1Password CLI (preferred) or SDK (fallback).
    """
    op_entries = {k: v for k, v in values.items() if v.startswith(OP_REF_PREFIX)}
    plain_entries = {k: v for k, v in values.items() if not v.startswith(OP_REF_PREFIX)}

    if not op_entries:
        return dict(values)

    lines = [f"{name}={ref}" for name, ref in op_entries.items()]
    content = "\n".join(lines)
    refs, line_to_ref = _extract_op_refs(lines)

    cli_error_msg: str | None = None
    try:
        env = os.environ.copy()
        env.update(_resolve_cli_env(config_root))
        result = subprocess.run(
            ["op", "inject"],
            input=content,
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        resolved_op = parse_injected_env(result.stdout)
        return {**plain_entries, **resolved_op}
    except subprocess.CalledProcessError as exc:
        cli_error_msg = _format_cli_error(exc.stderr or "")
    except Exception as exc:
        cli_error_msg = str(exc)

    try:
        resolved_op = asyncio.run(
            _resolve_op_refs_async(refs, lines, line_to_ref, config_root)
        )
        return {**plain_entries, **resolved_op}
    except Exception as sdk_error:
        raise RuntimeError(
            f"Failed to resolve 1Password references.\nCLI: {cli_error_msg}\nSDK: {sdk_error}"
        ) from sdk_error


def _format_sdk_failures(failures: list[tuple[str, object]]) -> str:
    """Format SDK resolution failures, grouping vault-level errors."""
    vault_not_found: set[str] = set()
    other: list[str] = []

    for ref, error in failures:
        err_str = str(error)
        if "vaultNotFound" in err_str:
            parts = ref.removeprefix(OP_REF_PREFIX).split("/", 2)
            vault_not_found.add(parts[0])
        else:
            other.append(f"  {ref}: {error}")

    msgs: list[str] = []
    if vault_not_found:
        names = ", ".join(f"'{v}'" for v in sorted(vault_not_found))
        msgs.append(
            f"Vault not found: {names}. "
            "Run `op vault list` to verify the name and check your OP_ACCOUNT."
        )
    if other:
        msgs.append("Failed to resolve references:\n" + "\n".join(other))
    return "\n".join(msgs)


async def _resolve_op_refs_async(
    refs: list[str],
    lines: list[str],
    line_to_ref: dict[int, str],
    config_root: Path | None,
) -> dict[str, str]:
    auth = _resolve_auth(config_root)
    client = await Client.authenticate(
        auth=auth,
        integration_name="ai-sync",
        integration_version="0.1.0",
    )
    response = await client.secrets.resolve_all(refs)
    failures: list[tuple[str, object]] = []
    resolved: dict[str, str] = {}
    for ref, resp in response.individual_responses.items():
        if resp.error is not None:
            failures.append((ref, resp.error))
        elif resp.content:
            resolved[ref] = resp.content.secret
    if failures:
        raise RuntimeError(_format_sdk_failures(failures))
    injected = _inject_resolved(lines, line_to_ref, resolved)
    return parse_injected_env(injected)
